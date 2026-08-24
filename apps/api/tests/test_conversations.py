"""Whose history is it, and can it become evidence.

ACT-001 Workstream E. Two families of test, and they fail in different directions:

  ownership   another account's conversation is a 404, not a 403, and not a redacted
              version of itself. Every read, every write, every archive.
  evidence    an assistant message is stored as an assistant message and there is no
              method anywhere that returns history to a retriever.

The second is asserted structurally as well as behaviourally. A behavioural test can only
show that today's code does not feed history back; the structural one shows that the
service has no method that could.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from uuid import uuid4

import pytest
from korpus.application.conversations import (
    MAX_MESSAGES_PER_CONVERSATION,
    ConversationLimitReached,
    ConversationService,
)
from korpus.application.tenancy_ports import ConversationArchived, ConversationNotFound
from korpus.domain.tenancy import MessageRole

from apps.api.tests.tenancy_fixtures import build_tenancy, reader


def _two_accounts(tenancy: object) -> tuple[object, object]:
    first = tenancy.account_service.require_active_account(reader("oidc|first"))  # type: ignore[attr-defined]
    second = tenancy.account_service.require_active_account(reader("oidc|second"))  # type: ignore[attr-defined]
    return first, second


def test_a_conversation_is_visible_only_to_its_owner(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        owner, stranger = _two_accounts(tenancy)
        service: ConversationService = tenancy.conversation_service
        conversation = service.create(owner, "накладання турнікету")

        assert service.get(owner, conversation.id).id == conversation.id
        with pytest.raises(ConversationNotFound):
            service.get(stranger, conversation.id)

        assert [item.id for item in service.list_conversations(owner).items] == [conversation.id]
        assert service.list_conversations(stranger).items == []
    finally:
        tenancy.close()


def test_another_accounts_messages_cannot_be_read(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        owner, stranger = _two_accounts(tenancy)
        service = tenancy.conversation_service
        conversation = service.create(owner)
        service.record_question(owner, conversation.id, "як накласти турнікет")

        assert len(service.messages(owner, conversation.id).items) == 1
        with pytest.raises(ConversationNotFound):
            service.messages(stranger, conversation.id)
    finally:
        tenancy.close()


def test_another_account_cannot_append_to_or_archive_a_conversation(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        owner, stranger = _two_accounts(tenancy)
        service = tenancy.conversation_service
        conversation = service.create(owner)

        with pytest.raises(ConversationNotFound):
            service.record_question(stranger, conversation.id, "чуже питання")
        with pytest.raises(ConversationNotFound):
            service.archive(stranger, conversation.id)

        assert service.get(owner, conversation.id).archived_at is None
        assert service.messages(owner, conversation.id).items == []
    finally:
        tenancy.close()


def test_an_unknown_conversation_and_a_foreign_one_are_the_same_refusal(
    tmp_path: Path,
) -> None:
    """Distinguishing them tells a caller that the id they guessed is real."""
    tenancy = build_tenancy(tmp_path)
    try:
        owner, stranger = _two_accounts(tenancy)
        service = tenancy.conversation_service
        conversation = service.create(owner)

        with pytest.raises(ConversationNotFound) as foreign:
            service.get(stranger, conversation.id)
        with pytest.raises(ConversationNotFound) as absent:
            service.get(stranger, uuid4())
        assert type(foreign.value) is type(absent.value)
        assert foreign.value.reason == absent.value.reason
    finally:
        tenancy.close()


def test_an_archived_conversation_takes_no_more_questions(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        owner, _stranger = _two_accounts(tenancy)
        service = tenancy.conversation_service
        conversation = service.create(owner)
        service.archive(owner, conversation.id)

        with pytest.raises(ConversationArchived):
            service.record_question(owner, conversation.id, "пізно")
        with pytest.raises(ConversationArchived):
            service.archive(owner, conversation.id)
    finally:
        tenancy.close()


def test_what_the_system_said_is_stored_as_the_system_having_said_it(
    tmp_path: Path,
) -> None:
    """The evidence boundary, as a stored fact rather than a convention."""
    tenancy = build_tenancy(tmp_path)
    try:
        owner, _stranger = _two_accounts(tenancy)
        service = tenancy.conversation_service
        conversation = service.create(owner)
        answer_id = uuid4()

        service.record_question(owner, conversation.id, "як накласти турнікет")
        service.record_answer(owner, conversation.id, "Витяг із настанови.", answer_id)

        stored = service.messages(owner, conversation.id).items
        assert [message.role for message in stored] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
        ]
        # A pointer, not a copy: the citations live with the answer and its audit event.
        assert stored[1].answer_id == answer_id
    finally:
        tenancy.close()


def test_the_conversation_service_offers_no_way_to_turn_history_into_evidence() -> None:
    """Structural. A behavioural test shows today's code does not; this shows it cannot.

    Nothing here returns spans, evidence or a retriever's input. The only thing a caller
    can get out is `MessageRecord`s, which carry a role — so anything that did try to feed
    them back would have to strip that first, visibly.
    """
    returns = {
        name: inspect.signature(member).return_annotation
        for name, member in inspect.getmembers(ConversationService, inspect.isfunction)
        if not name.startswith("_")
    }
    assert returns, "the service exposes no methods — this test is stale"
    for name, annotation in returns.items():
        text = str(annotation)
        assert "Evidence" not in text and "Span" not in text, (
            f"ConversationService.{name} returns retrieval material"
        )


def test_a_conversation_will_not_grow_without_limit(tmp_path: Path) -> None:
    """Unbounded history is an unbounded response and an unbounded row count."""
    tenancy = build_tenancy(tmp_path)
    try:
        owner, _stranger = _two_accounts(tenancy)
        service = tenancy.conversation_service
        conversation = service.create(owner)

        from datetime import UTC, datetime

        from korpus.domain.tenancy import MessageRecord

        # Written through the store so the test costs one insert per row rather than a
        # full list scan per row; the limit itself is then exercised through the service.
        for index in range(MAX_MESSAGES_PER_CONVERSATION):
            tenancy.conversations.append_message(
                owner.id,
                MessageRecord(
                    conversation_id=conversation.id,
                    role=MessageRole.USER,
                    raw_text=f"питання {index}",
                    created_at=datetime.now(UTC),
                ),
            )

        with pytest.raises(ConversationLimitReached):
            service.record_question(owner, conversation.id, "ще одне")
    finally:
        tenancy.close()


def test_an_empty_or_oversized_question_is_refused(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        owner, _stranger = _two_accounts(tenancy)
        service = tenancy.conversation_service
        conversation = service.create(owner)

        with pytest.raises(ValueError):
            service.record_question(owner, conversation.id, "   ")
        with pytest.raises(ValueError):
            service.record_question(owner, conversation.id, "я" * 4001)
    finally:
        tenancy.close()


def test_purging_an_account_removes_its_history_and_nobody_elses(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        owner, stranger = _two_accounts(tenancy)
        service = tenancy.conversation_service
        mine = service.create(owner)
        theirs = service.create(stranger)
        service.record_question(owner, mine.id, "моє питання")
        service.record_question(stranger, theirs.id, "їхнє питання")

        removed = tenancy.conversations.purge_account(owner.id)

        assert removed == 1
        assert service.list_conversations(owner).items == []
        assert [item.id for item in service.list_conversations(stranger).items] == [theirs.id]
        assert len(service.messages(stranger, theirs.id).items) == 1
    finally:
        tenancy.close()


def test_a_stored_answer_remembers_whether_it_was_one(tmp_path: Path) -> None:
    """Found by reading a transcript in a browser, not by a test.

    History rendered a refusal — "недостатньо доказів" — in the same shape as an answer,
    because the verdict was never stored. The citations can be checked against the corpus
    at any time; the verdict cannot be recomputed, since the corpus moves and the same
    question tomorrow may be answered.
    """
    tenancy = build_tenancy(tmp_path)
    try:
        owner, _stranger = _two_accounts(tenancy)
        service = tenancy.conversation_service
        conversation = service.create(owner)

        service.record_question(owner, conversation.id, "перше")
        service.record_answer(owner, conversation.id, "Витяг.", uuid4(), "answered")
        service.record_question(owner, conversation.id, "друге")
        service.record_answer(
            owner, conversation.id, "Недостатньо доказів.", uuid4(), "insufficient_evidence"
        )

        stored = service.messages(owner, conversation.id).items
        assert [message.answer_status for message in stored] == [
            None,
            "answered",
            None,
            "insufficient_evidence",
        ]
    finally:
        tenancy.close()


def test_a_turn_stored_before_the_verdict_existed_reports_it_as_unrecorded(
    tmp_path: Path,
) -> None:
    """`None`, not `answered`. Assuming is the failure being fixed."""
    tenancy = build_tenancy(tmp_path)
    try:
        owner, _stranger = _two_accounts(tenancy)
        conversation = tenancy.conversation_service.create(owner)
        tenancy.conversation_service.record_answer(owner, conversation.id, "Стара відповідь.", None)
        stored = tenancy.conversation_service.messages(owner, conversation.id).items
        assert stored[0].answer_status is None
    finally:
        tenancy.close()


def test_a_truncated_list_says_it_was_truncated(tmp_path: Path) -> None:
    """The defect this replaces: the list stopped at fifty and said nothing.

    A reader with a hundred conversations saw fifty, which reads as an account that has
    fifty. Over-fetching one row answers "is there more" without a second scan of every
    row the account owns.
    """
    tenancy = build_tenancy(tmp_path)
    try:
        owner, _stranger = _two_accounts(tenancy)
        service = tenancy.conversation_service
        for index in range(7):
            service.create(owner, f"розмова {index}")

        page = service.list_conversations(owner, limit=3)
        assert len(page.items) == 3
        assert page.has_more is True
        assert page.next_offset == 3

        second = service.list_conversations(owner, limit=3, offset=3)
        assert len(second.items) == 3
        assert second.has_more is True
        # No overlap: page two starts where page one stopped.
        assert not {item.id for item in page.items} & {item.id for item in second.items}

        last = service.list_conversations(owner, limit=3, offset=6)
        assert len(last.items) == 1
        assert last.has_more is False
        assert last.next_offset is None
    finally:
        tenancy.close()


def test_an_exact_page_does_not_claim_there_is_more(tmp_path: Path) -> None:
    """The off-by-one. `has_more` true on a complete list is as useless as never true."""
    tenancy = build_tenancy(tmp_path)
    try:
        owner, _stranger = _two_accounts(tenancy)
        for index in range(3):
            tenancy.conversation_service.create(owner, f"р{index}")
        page = tenancy.conversation_service.list_conversations(owner, limit=3)
        assert len(page.items) == 3
        assert page.has_more is False
    finally:
        tenancy.close()


def test_a_truncated_transcript_says_its_newest_turns_are_missing(tmp_path: Path) -> None:
    """A transcript is read oldest-first, so a cut removes what somebody came back for."""
    from datetime import UTC, datetime

    from korpus.domain.tenancy import MessageRecord

    tenancy = build_tenancy(tmp_path)
    try:
        owner, _stranger = _two_accounts(tenancy)
        conversation = tenancy.conversation_service.create(owner)
        for index in range(5):
            tenancy.conversations.append_message(
                owner.id,
                MessageRecord(
                    conversation_id=conversation.id,
                    role=MessageRole.USER,
                    raw_text=f"хід {index}",
                    created_at=datetime.now(UTC),
                ),
            )

        page = tenancy.conversation_service.messages(owner, conversation.id, limit=2)
        assert [message.raw_text for message in page.items] == ["хід 0", "хід 1"]
        assert page.has_more is True
        assert page.next_offset == 2
    finally:
        tenancy.close()


def test_the_message_limit_is_checked_without_reading_the_whole_conversation(
    tmp_path: Path,
) -> None:
    """The limit check used to read five hundred rows to answer a yes/no question.

    Every question asked in a long conversation paid for the whole conversation. It now
    asks for the one row at the boundary.
    """
    from datetime import UTC, datetime

    from korpus.domain.tenancy import MessageRecord

    tenancy = build_tenancy(tmp_path)
    try:
        owner, _stranger = _two_accounts(tenancy)
        conversation = tenancy.conversation_service.create(owner)
        for index in range(MAX_MESSAGES_PER_CONVERSATION):
            tenancy.conversations.append_message(
                owner.id,
                MessageRecord(
                    conversation_id=conversation.id,
                    role=MessageRole.USER,
                    raw_text=f"хід {index}",
                    created_at=datetime.now(UTC),
                ),
            )

        reads: list[int] = []
        original = tenancy.conversations.list_messages

        def counted(*args: object, **kwargs: object) -> object:
            reads.append(int(kwargs.get("limit", 0)))
            return original(*args, **kwargs)  # type: ignore[arg-type]

        tenancy.conversations.list_messages = counted  # type: ignore[method-assign]
        try:
            with pytest.raises(ConversationLimitReached):
                tenancy.conversation_service.record_question(owner, conversation.id, "ще")
        finally:
            tenancy.conversations.list_messages = original  # type: ignore[method-assign]

        assert reads == [1], f"the limit check read {reads} rows to answer a yes/no question"
    finally:
        tenancy.close()
