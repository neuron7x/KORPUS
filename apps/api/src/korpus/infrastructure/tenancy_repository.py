"""Accounts in SQL, sharing the corpus database and its audit chain.

One property is enforced here rather than above, because a service cannot enforce it:
first login is idempotent under concurrency, by `uq_accounts_auth_subject` and an INSERT
that is allowed to lose. A read-then-write is a race, and two tabs opening at once is the
normal shape of a first login, not an exotic one.

Conversation history lives in `conversation_repository.py`; it shares `aware` and
`system_actor` from here.

State changes travel with their audit event in one commit — `audited_transaction` on the
corpus repository — so there is no window in which an account is disabled and nothing
records who did it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from korpus.application.tenancy_ports import AccountNotFound
from korpus.domain.models import Identity
from korpus.domain.tenancy import AccountRecord, AccountStatus
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.tenancy_schema import accounts


def aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes for `DateTime(timezone=True)` columns.

    Left naive they compare falsely against `datetime.now(UTC)` — `TypeError` at best,
    and at worst a period-end check that silently does the wrong thing on one dialect
    and the right thing on the other.
    """
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _account(row: Any) -> AccountRecord:
    return AccountRecord(
        id=UUID(row["id"]),
        auth_subject=row["auth_subject"],
        email=row["email"],
        display_name=row["display_name"],
        status=AccountStatus(row["status"]),
        created_at=aware(row["created_at"]),
        updated_at=aware(row["updated_at"]),
        disabled_at=aware(row["disabled_at"]),
    )


def system_actor(subject: str) -> Identity:
    """A name for the audit chain that carries no reading rights.

    Account and billing events are attributed to the subject that caused them, and that
    subject must not acquire rights by being named in an audit call. `roles` is empty,
    which is what makes this inert: `PolicyEngine.permissions` returns nothing for it, so
    `require` refuses every permission including `answer:read`.

    The corpus is `public` rather than nothing because `Identity` refuses an empty set —
    an identity that holds no corpus is a bug everywhere else in this system, and
    weakening that invariant to build an audit actor would be paying for a label with a
    check. With no roles the value is unreachable.
    """
    from korpus.domain.models import AccessTier

    return Identity(
        subject=subject,
        roles=frozenset(),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
        compartments=frozenset(),
    )


class SqlAccountStore:
    def __init__(self, repository: SqlRepository) -> None:
        self._repository = repository
        self.engine = repository.engine

    def ensure_account(
        self,
        auth_subject: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
    ) -> tuple[AccountRecord, bool]:
        existing = self.get_account_by_subject(auth_subject)
        if existing is not None:
            return existing, False

        record = AccountRecord(
            auth_subject=auth_subject, email=email, display_name=display_name
        )

        def operation(connection: Connection) -> tuple[AccountRecord, tuple[int, str]]:
            connection.execute(
                insert(accounts).values(
                    id=str(record.id),
                    auth_subject=record.auth_subject,
                    email=record.email,
                    display_name=record.display_name,
                    status=record.status.value,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    disabled_at=None,
                )
            )
            anchor = self._repository.audit_in_connection(
                connection,
                system_actor(auth_subject),
                "account.created",
                "account",
                str(record.id),
                {
                    "auth_subject": auth_subject,
                    "has_email": email is not None,
                    "interpretation": (
                        "An application account was created for an authenticated subject. "
                        "It grants no corpus authorization: what may be read is decided by "
                        "the entitlement profile and the policy engine, neither of which "
                        "reads this table."
                    ),
                },
            )
            return record, anchor

        try:
            return self._repository.audited_transaction(operation), True
        except IntegrityError:
            # Lost the race. The other writer's row is the account — returning ours would
            # mean two account ids for one subject, and every later read would pick
            # whichever the unique constraint kept.
            winner = self.get_account_by_subject(auth_subject)
            if winner is None:  # pragma: no cover - the constraint that raised guarantees it
                raise
            return winner, False

    def get_account(self, account_id: UUID) -> AccountRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(accounts).where(accounts.c.id == str(account_id)))
                .mappings()
                .first()
            )
        return _account(row) if row else None

    def get_account_by_subject(self, auth_subject: str) -> AccountRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(accounts).where(accounts.c.auth_subject == auth_subject)
                )
                .mappings()
                .first()
            )
        return _account(row) if row else None

    def list_accounts(
        self, *, limit: int = 50, offset: int = 0, disabled_only: bool = False
    ) -> tuple[list[AccountRecord], bool]:
        """Accounts, newest first, and whether there are more.

        Unscoped and reachable only from the admin routes: every other read in this file
        is by id or by subject, because a request must never be able to enumerate who
        exists. Over-fetches one row for the same reason the conversation list does — a
        page that stops without saying so reports a truncation as a fact about the system.
        """
        wanted = max(1, min(limit, 200))
        statement = (
            select(accounts)
            .order_by(accounts.c.created_at.desc(), accounts.c.id)
            .limit(wanted + 1)
            .offset(max(0, offset))
        )
        if disabled_only:
            statement = statement.where(accounts.c.status == AccountStatus.DISABLED.value)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [_account(row) for row in rows[:wanted]], len(rows) > wanted

    def set_account_status(
        self,
        actor_subject: str,
        account_id: UUID,
        status: AccountStatus,
        *,
        reason: str,
    ) -> AccountRecord:
        moment = datetime.now(UTC)

        def operation(connection: Connection) -> tuple[AccountRecord, tuple[int, str]]:
            row = (
                connection.execute(select(accounts).where(accounts.c.id == str(account_id)))
                .mappings()
                .first()
            )
            if row is None:
                raise AccountNotFound(str(account_id))
            connection.execute(
                update(accounts)
                .where(accounts.c.id == str(account_id))
                .values(
                    status=status.value,
                    updated_at=moment,
                    # Cleared on re-enable: a timestamp left behind says the account is
                    # still disabled to anyone reading the column instead of the status.
                    disabled_at=moment if status is AccountStatus.DISABLED else None,
                )
            )
            anchor = self._repository.audit_in_connection(
                connection,
                system_actor(actor_subject),
                f"account.{status.value}",
                "account",
                str(account_id),
                {
                    "previous_status": row["status"],
                    "status": status.value,
                    "reason": reason,
                    "interpretation": (
                        "A disabled account is refused before any corpus work happens. "
                        "Disabling is reversible and the event is not: both directions are "
                        "recorded."
                    ),
                },
            )
            updated = AccountRecord(
                id=UUID(row["id"]),
                auth_subject=row["auth_subject"],
                email=row["email"],
                display_name=row["display_name"],
                status=status,
                created_at=aware(row["created_at"]),
                updated_at=moment,
                disabled_at=moment if status is AccountStatus.DISABLED else None,
            )
            return updated, anchor

        return self._repository.audited_transaction(operation)
