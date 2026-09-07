from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, or_, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectReservation,
    EffectState,
    InvalidEffectTransition,
    ReconciliationDisposition,
    assert_effect_transition,
)
from korpus.infrastructure.capability_effect_schema import capability_effects
from korpus.infrastructure.schema import metadata

# Backward-compatible test/export name. This is deliberately the canonical metadata now,
# not a private island that production startup and Alembic can fail to see.
capability_effect_metadata = metadata

SubjectIdentityBinder = Callable[[Connection, str], None]


class EffectLedgerConflict(RuntimeError):
    pass


class SqlEffectLedger:
    """Durable compare-and-set ledger for governed capability side effects.

    PostgreSQL requires an injected subject binder. Each ledger transaction binds the
    already-authenticated KORPUS subject before touching the FORCE-RLS table. The binder is
    infrastructure-owned composition; request bodies, provider metadata and adapters never
    get to choose it. SQLite has no RLS and remains the local/test profile.

    Ambiguous effects are reconciled through `reconcile`, not generic `transition`: a
    RECONCILED row is invalid unless its durable disposition is explicit.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        bind_subject: SubjectIdentityBinder | None = None,
    ) -> None:
        if engine.dialect.name == "postgresql" and bind_subject is None:
            raise ValueError("PostgreSQL effect ledger requires a trusted subject identity binder")
        self.engine = engine
        self._bind_subject = bind_subject
        self._sqlite_lock = threading.RLock()

    def reserve(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        binding_digest: str,
        invocation_id: str,
        capability_id: str,
        capability_version: str,
        logical_resource: str,
        input_digest: str,
    ) -> EffectReservation:
        current = datetime.now(UTC)
        values = {
            "subject_id": subject_id,
            "idempotency_key": idempotency_key,
            "binding_digest": binding_digest,
            "invocation_id": invocation_id,
            "capability_id": capability_id,
            "capability_version": capability_version,
            "logical_resource": logical_resource,
            "input_digest": input_digest,
            "state": EffectState.PENDING.value,
            "provider_reference": None,
            "reconciliation_disposition": None,
            "created_at": current,
            "updated_at": current,
        }
        guard = self._sqlite_lock if self.engine.dialect.name == "sqlite" else nullcontext()
        with guard:
            try:
                with self.engine.begin() as connection:
                    self._bind(connection, subject_id)
                    connection.execute(insert(capability_effects).values(**values))
                return EffectReservation(record=self._record(values), created=True)
            except IntegrityError:
                with self.engine.begin() as connection:
                    self._bind(connection, subject_id)
                    row = (
                        connection.execute(
                            select(capability_effects)
                            .where(capability_effects.c.subject_id == subject_id)
                            .where(capability_effects.c.idempotency_key == idempotency_key)
                        )
                        .mappings()
                        .first()
                    )
                if row is None:
                    raise
                return EffectReservation(record=self._record(row), created=False)

    def transition(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected: EffectState,
        target: EffectState,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        if target is EffectState.RECONCILED:
            raise InvalidEffectTransition(
                "RECONCILED requires an explicit disposition via SqlEffectLedger.reconcile"
            )
        assert_effect_transition(expected, target)
        current = datetime.now(UTC)
        guard = self._sqlite_lock if self.engine.dialect.name == "sqlite" else nullcontext()
        with guard, self.engine.begin() as connection:
            self._bind(connection, subject_id)
            changed = connection.execute(
                update(capability_effects)
                .where(capability_effects.c.subject_id == subject_id)
                .where(capability_effects.c.idempotency_key == idempotency_key)
                .where(capability_effects.c.state == expected.value)
                .values(
                    state=target.value,
                    provider_reference=provider_reference,
                    updated_at=current,
                )
            )
            if changed.rowcount != 1:
                row = (
                    connection.execute(
                        select(capability_effects)
                        .where(capability_effects.c.subject_id == subject_id)
                        .where(capability_effects.c.idempotency_key == idempotency_key)
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise EffectLedgerConflict("effect reservation does not exist")
                actual = EffectState(str(row["state"]))
                try:
                    assert_effect_transition(actual, target)
                except InvalidEffectTransition as exc:
                    raise EffectLedgerConflict(
                        f"effect transition changed concurrently: {actual.value} -> {target.value}"
                    ) from exc
                raise EffectLedgerConflict(
                    f"effect state changed concurrently: expected {expected.value}, got {actual.value}"
                )
            row = (
                connection.execute(
                    select(capability_effects)
                    .where(capability_effects.c.subject_id == subject_id)
                    .where(capability_effects.c.idempotency_key == idempotency_key)
                )
                .mappings()
                .one()
            )
        return self._record(row)

    def reconcile(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected_binding_digest: str,
        disposition: ReconciliationDisposition,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        """Atomically resolve OUTCOME_UNKNOWN to RECONCILED with an explicit disposition."""

        if not isinstance(disposition, ReconciliationDisposition):
            raise ValueError("reconciliation disposition must be a registered enum value")
        if provider_reference is not None:
            if not isinstance(provider_reference, str) or not provider_reference.strip():
                raise ValueError("provider reference must be a non-blank string")
            if len(provider_reference) > 512:
                raise ValueError("provider reference exceeds maximum length")

        current = datetime.now(UTC)
        guard = self._sqlite_lock if self.engine.dialect.name == "sqlite" else nullcontext()
        with guard, self.engine.begin() as connection:
            self._bind(connection, subject_id)
            statement = (
                update(capability_effects)
                .where(capability_effects.c.subject_id == subject_id)
                .where(capability_effects.c.idempotency_key == idempotency_key)
                .where(capability_effects.c.binding_digest == expected_binding_digest)
                .where(capability_effects.c.state == EffectState.OUTCOME_UNKNOWN.value)
            )
            if provider_reference is not None:
                statement = statement.where(
                    or_(
                        capability_effects.c.provider_reference.is_(None),
                        capability_effects.c.provider_reference == provider_reference,
                    )
                )
            values: dict[str, object] = {
                "state": EffectState.RECONCILED.value,
                "reconciliation_disposition": disposition.value,
                "updated_at": current,
            }
            if provider_reference is not None:
                values["provider_reference"] = provider_reference
            changed = connection.execute(statement.values(**values))
            if changed.rowcount != 1:
                row = (
                    connection.execute(
                        select(capability_effects)
                        .where(capability_effects.c.subject_id == subject_id)
                        .where(capability_effects.c.idempotency_key == idempotency_key)
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise EffectLedgerConflict("effect reservation does not exist")
                if str(row["binding_digest"]) != expected_binding_digest:
                    raise EffectLedgerConflict("effect reconciliation binding mismatch")
                actual = EffectState(str(row["state"]))
                if actual is not EffectState.OUTCOME_UNKNOWN:
                    raise EffectLedgerConflict(
                        f"effect is not reconcilable from state {actual.value}"
                    )
                current_reference = row["provider_reference"]
                if (
                    provider_reference is not None
                    and current_reference is not None
                    and str(current_reference) != provider_reference
                ):
                    raise EffectLedgerConflict("provider reference changed before reconciliation")
                raise EffectLedgerConflict("effect reconciliation compare-and-set failed")
            row = (
                connection.execute(
                    select(capability_effects)
                    .where(capability_effects.c.subject_id == subject_id)
                    .where(capability_effects.c.idempotency_key == idempotency_key)
                )
                .mappings()
                .one()
            )
        return self._record(row)

    def get(self, *, subject_id: str, idempotency_key: str) -> EffectRecord | None:
        with self.engine.begin() as connection:
            self._bind(connection, subject_id)
            row = (
                connection.execute(
                    select(capability_effects)
                    .where(capability_effects.c.subject_id == subject_id)
                    .where(capability_effects.c.idempotency_key == idempotency_key)
                )
                .mappings()
                .first()
            )
        return self._record(row) if row is not None else None

    def _bind(self, connection: Connection, subject_id: str) -> None:
        if self.engine.dialect.name != "postgresql":
            return
        binder = self._bind_subject
        if binder is None:
            # Constructor rejects this state for PostgreSQL. Keep the runtime assertion so
            # monkeypatching or deserialization cannot silently turn RLS into an empty context.
            raise RuntimeError("trusted effect-ledger subject binder is unavailable")
        binder(connection, subject_id)

    @staticmethod
    def _record(row: Any) -> EffectRecord:
        disposition = row["reconciliation_disposition"]
        return EffectRecord(
            subject_id=str(row["subject_id"]),
            idempotency_key=str(row["idempotency_key"]),
            binding_digest=str(row["binding_digest"]),
            invocation_id=str(row["invocation_id"]),
            capability_id=str(row["capability_id"]),
            capability_version=str(row["capability_version"]),
            logical_resource=str(row["logical_resource"]),
            input_digest=str(row["input_digest"]),
            state=EffectState(str(row["state"])),
            provider_reference=(
                str(row["provider_reference"]) if row["provider_reference"] is not None else None
            ),
            reconciliation_disposition=(
                ReconciliationDisposition(str(disposition)) if disposition is not None else None
            ),
        )
