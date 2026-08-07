"""Conversation history in SQL. Every query carries the owner.

Split from `tenancy_repository.py`: accounts are identity and this is content, and the one
rule that matters here does not apply there. Every method takes an `account_id` and puts it
in the WHERE clause. Filtering after the fetch is one forgotten line away from serving
another account's history, and the forgotten line is invisible in review because the happy
path looks identical either way.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, select, update

from korpus.application.tenancy_ports import ConversationArchived, ConversationNotFound
from korpus.domain.tenancy import ConversationRecord, MessageRecord, MessageRole
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.tenancy_repository import aware
from korpus.infrastructure.tenancy_schema import conversations, messages


def _conversation(row: Any) -> ConversationRecord:
    return ConversationRecord(
        id=UUID(row["id"]),
        account_id=UUID(row["account_id"]),
        title=row["title"],
        created_at=aware(row["created_at"]),
        updated_at=aware(row["updated_at"]),
        archived_at=aware(row["archived_at"]),
    )


def _message(row: Any) -> MessageRecord:
    return MessageRecord(
        id=UUID(row["id"]),
        conversation_id=UUID(row["conversation_id"]),
        role=MessageRole(row["role"]),
        raw_text=row["raw_text"],
        answer_id=UUID(row["answer_id"]) if row["answer_id"] else None,
        created_at=aware(row["created_at"]),
    )


class SqlConversationStore:
    """Conversation history. Every query carries the owner; none of them takes it on trust."""

    def __init__(self, repository: SqlRepository) -> None:
        self._repository = repository
        self.engine = repository.engine

    def create_conversation(self, conversation: ConversationRecord) -> ConversationRecord:
        with self.engine.begin() as connection:
            connection.execute(
                insert(conversations).values(
                    id=str(conversation.id),
                    account_id=str(conversation.account_id),
                    title=conversation.title,
                    created_at=conversation.created_at,
                    updated_at=conversation.updated_at,
                    archived_at=None,
                )
            )
        return conversation

    def list_conversations(
        self, account_id: UUID, *, include_archived: bool = False, limit: int = 50
    ) -> list[ConversationRecord]:
        statement = (
            select(conversations)
            .where(conversations.c.account_id == str(account_id))
            .order_by(conversations.c.updated_at.desc(), conversations.c.id)
            .limit(max(1, min(limit, 200)))
        )
        if not include_archived:
            statement = statement.where(conversations.c.archived_at.is_(None))
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [_conversation(row) for row in rows]

    def get_conversation(
        self, account_id: UUID, conversation_id: UUID
    ) -> ConversationRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(conversations)
                    .where(conversations.c.id == str(conversation_id))
                    # The ownership predicate is in the query. A caller cannot forget it,
                    # because there is no overload without it.
                    .where(conversations.c.account_id == str(account_id))
                )
                .mappings()
                .first()
            )
        return _conversation(row) if row else None

    def archive_conversation(
        self, account_id: UUID, conversation_id: UUID
    ) -> ConversationRecord:
        moment = datetime.now(UTC)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(conversations)
                .where(conversations.c.id == str(conversation_id))
                .where(conversations.c.account_id == str(account_id))
                .where(conversations.c.archived_at.is_(None))
                .values(archived_at=moment, updated_at=moment)
            )
            if result.rowcount != 1:
                # Not found, not owned, or already archived. One exception for the first
                # two on purpose: telling an unauthorized caller that the id is real is
                # half of what enumeration needs.
                row = (
                    connection.execute(
                        select(conversations)
                        .where(conversations.c.id == str(conversation_id))
                        .where(conversations.c.account_id == str(account_id))
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise ConversationNotFound(str(conversation_id))
                raise ConversationArchived(str(conversation_id))
        found = self.get_conversation(account_id, conversation_id)
        if found is None:  # pragma: no cover - the update above found the row
            raise ConversationNotFound(str(conversation_id))
        return found

    def append_message(self, account_id: UUID, message: MessageRecord) -> MessageRecord:
        with self.engine.begin() as connection:
            owner = connection.execute(
                select(conversations.c.archived_at)
                .where(conversations.c.id == str(message.conversation_id))
                .where(conversations.c.account_id == str(account_id))
            ).first()
            if owner is None:
                raise ConversationNotFound(str(message.conversation_id))
            if owner[0] is not None:
                raise ConversationArchived(str(message.conversation_id))
            connection.execute(
                insert(messages).values(
                    id=str(message.id),
                    conversation_id=str(message.conversation_id),
                    role=message.role.value,
                    raw_text=message.raw_text,
                    answer_id=str(message.answer_id) if message.answer_id else None,
                    created_at=message.created_at,
                )
            )
            connection.execute(
                update(conversations)
                .where(conversations.c.id == str(message.conversation_id))
                .values(updated_at=message.created_at)
            )
        return message

    def list_messages(
        self, account_id: UUID, conversation_id: UUID, *, limit: int = 200
    ) -> list[MessageRecord]:
        statement = (
            select(messages)
            .join(conversations, messages.c.conversation_id == conversations.c.id)
            .where(messages.c.conversation_id == str(conversation_id))
            .where(conversations.c.account_id == str(account_id))
            .order_by(messages.c.created_at, messages.c.id)
            .limit(max(1, min(limit, 500)))
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [_message(row) for row in rows]

    def purge_account(self, account_id: UUID) -> int:
        """Erase one account's history. Used by the retention path, not by the API.

        Messages first: the foreign key cascades, but relying on a cascade to do the
        deletion means the count returned here is whatever the driver felt like
        reporting, and a retention job that cannot say how much it deleted is a job
        nobody can check.
        """
        with self.engine.begin() as connection:
            owned = select(conversations.c.id).where(
                conversations.c.account_id == str(account_id)
            )
            removed = connection.execute(
                delete(messages).where(messages.c.conversation_id.in_(owned))
            ).rowcount
            connection.execute(
                delete(conversations).where(conversations.c.account_id == str(account_id))
            )
        return int(removed or 0)
