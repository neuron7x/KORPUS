"""A conversation is context. It is never evidence.

The distinction is the reason this module is small and unexciting: it stores what was
asked and what was answered, and provides no way for any of it to re-enter the answer path
as a source.

A retrieval-augmented system with history has one characteristic failure. Turn one cites a
manual correctly. Turn two summarises turn one. Turn three cites the summary. By turn four
the system is quoting itself with a citation list that looks complete, and every sentence
in it traces back to a claim the system invented. `MessageRole.ASSISTANT` exists so that
boundary is a type rather than a discipline, and `ConversationService` deliberately has no
method that returns history to a retriever.

What history is for: the person reading it. That is worth keeping — a soldier who asked
three questions under fire needs to see what they were told — and it is worth keeping in a
place that cannot leak into `list_retrievable_spans`.

Ownership is checked in the query, not after it. Every method takes an `account_id` and
passes it to a store method that has no overload without one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from korpus.application.tenancy_ports import (
    ConversationNotFound,
    ConversationStore,
)
from korpus.domain.tenancy import (
    AccountRecord,
    ConversationRecord,
    MessageRecord,
    MessageRole,
)

#: A question longer than this is refused. The corpus answers questions, and a body this
#: size is either a paste of a document — which belongs in ingestion, under review — or an
#: attempt to fill the model's context with instructions.
MAX_QUESTION_CHARS = 4_000

#: How many turns one conversation may hold. Unbounded history is an unbounded row count
#: per account and an unbounded response from `list_messages`; both are somebody else's
#: outage.
MAX_MESSAGES_PER_CONVERSATION = 500


class ConversationLimitReached(RuntimeError):
    reason = "conversation_message_limit"


@dataclass(frozen=True)
class Page[T]:
    """A slice, and whether it is the whole thing.

    `has_more` exists because the alternative is silence, and silence is what this had:
    the list stopped at fifty and said nothing, which a reader takes as fifty being all
    there is. The corpus panel already names what it cut ("…і ще N"); this is the same
    rule applied where it was missing.

    No total. Counting every row an account owns to answer "is there more" is a second
    scan for a question nobody asked — the reader wants to know whether to keep looking,
    not the cardinality of their history.
    """

    items: list[T]
    has_more: bool
    offset: int
    limit: int

    @property
    def next_offset(self) -> int | None:
        return self.offset + len(self.items) if self.has_more else None


class ConversationService:
    def __init__(self, store: ConversationStore) -> None:
        self._store = store

    def create(self, account: AccountRecord, title: str | None = None) -> ConversationRecord:
        cleaned = (title or "").strip()[:200] or None
        conversation = ConversationRecord(account_id=account.id, title=cleaned)
        return self._store.create_conversation(conversation)

    # Not `list`: a method by that name shadows the builtin inside the class body, and
    # every `-> list[...]` annotation below it then refers to the method. mypy caught it;
    # at runtime it would have been a `TypeError` on the first annotation evaluated.
    def list_conversations(
        self,
        account: AccountRecord,
        *,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[ConversationRecord]:
        items, has_more = self._store.list_conversations(
            account.id, include_archived=include_archived, limit=limit, offset=offset
        )
        return Page(items=items, has_more=has_more, offset=offset, limit=limit)

    def get(self, account: AccountRecord, conversation_id: UUID) -> ConversationRecord:
        conversation = self._store.get_conversation(account.id, conversation_id)
        if conversation is None:
            # Also the answer when it exists and belongs to somebody else. Telling an
            # unauthorized caller that the id is real is half of what enumeration needs.
            raise ConversationNotFound(str(conversation_id))
        return conversation

    def archive(self, account: AccountRecord, conversation_id: UUID) -> ConversationRecord:
        return self._store.archive_conversation(account.id, conversation_id)

    def messages(
        self,
        account: AccountRecord,
        conversation_id: UUID,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> Page[MessageRecord]:
        self.get(account, conversation_id)
        items, has_more = self._store.list_messages(
            account.id, conversation_id, limit=limit, offset=offset
        )
        return Page(items=items, has_more=has_more, offset=offset, limit=limit)

    def record_question(
        self, account: AccountRecord, conversation_id: UUID, text: str
    ) -> MessageRecord:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("an empty question is not a question")
        if len(cleaned) > MAX_QUESTION_CHARS:
            raise ValueError(f"question exceeds {MAX_QUESTION_CHARS} characters")
        self._require_room(account, conversation_id)
        return self._store.append_message(
            account.id,
            MessageRecord(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                raw_text=cleaned,
                created_at=datetime.now(UTC),
            ),
        )

    def record_answer(
        self,
        account: AccountRecord,
        conversation_id: UUID,
        text: str,
        answer_id: UUID | None,
        status: str | None = None,
    ) -> MessageRecord:
        """Store what the system said, marked as the system having said it.

        `answer_id` points at the answer whose citations and audit event carry the actual
        evidence. Stored as a pointer rather than a copy so there is exactly one version of
        what was cited; a copy here would drift from the audit chain and there would be no
        way to tell which one a reader had seen.

        `status` is the exception to that, and it is one on purpose. The citations can be
        checked against the corpus at any time; the verdict cannot be recomputed — the
        corpus moves, the calibration moves, and the same question tomorrow may be refused.
        Without it a transcript renders a refusal as though it were an answer, which is the
        one distinction this interface exists to keep.
        """
        return self._store.append_message(
            account.id,
            MessageRecord(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                raw_text=text.strip()[:20_000] or "(відмова)",
                answer_id=answer_id,
                answer_status=status,
                created_at=datetime.now(UTC),
            ),
        )

    def _require_room(self, account: AccountRecord, conversation_id: UUID) -> None:
        # Asks for the last page rather than for all of them: the question is whether a
        # row exists at the limit, and reading five hundred rows to answer it made every
        # question in a long conversation cost the whole conversation.
        existing, _more = self._store.list_messages(
            account.id, conversation_id, limit=1, offset=MAX_MESSAGES_PER_CONVERSATION - 1
        )
        if existing:
            raise ConversationLimitReached(
                f"conversation holds the maximum of {MAX_MESSAGES_PER_CONVERSATION} messages"
            )
