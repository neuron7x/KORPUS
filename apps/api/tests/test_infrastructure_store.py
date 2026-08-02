"""The store: durability, idempotency, and recovery from a corrupt file."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from uuid import uuid4

from conftest import make_span
from korpus.domain.models import ReviewState
from korpus.infrastructure.store import CorpusStore


def open_store(tmp_path: Path) -> CorpusStore:
    return CorpusStore(tmp_path / "korpus.sqlite3")


def test_a_stored_chunk_comes_back_identical(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    span = make_span(text="порядок евакуації", review=ReviewState.APPROVED)
    assert store.add(span, "sha") is True
    restored = list(store.spans())
    assert len(restored) == 1
    kept = restored[0]
    assert kept.chunk_id == span.chunk_id
    assert kept.corpus_id == span.corpus_id
    assert kept.citation.quote == span.citation.quote
    assert kept.review_state is span.review_state


def test_the_same_chunk_is_not_stored_twice(tmp_path: Path) -> None:
    """Re-running an import on a bad connection must not double every citation."""
    store = open_store(tmp_path)
    span = make_span()
    assert store.add(span, "sha") is True
    assert store.add(span, "sha") is False
    assert store.count() == 1


def test_the_corpus_survives_a_restart(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.add(make_span(), "sha")
    store.close()
    reopened = open_store(tmp_path)
    assert reopened.count() == 1
    assert reopened.recovered is False


def test_supersession_retires_every_chunk_of_a_version(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    version, replacement = uuid4(), uuid4()
    store.add(make_span(version_id=version), "sha")
    store.add(make_span(version_id=version), "sha")
    store.add(make_span(), "sha")
    assert store.supersede(version, replacement) == 2
    retired = [s for s in store.spans() if s.superseded_by == replacement]
    assert len(retired) == 2


def test_audit_events_are_written_and_counted(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.record_audit("answer.completed", {"status": "answered"})
    store.record_audit("corpus.ingested", {"chunks": 4})
    assert store.audit_count() == 2


def test_a_corrupt_database_is_quarantined_and_rebuilt(tmp_path: Path) -> None:
    """The failure that must not take the process down with it.

    The file is overwritten with garbage between runs — a truncated write, a bad
    disk — and the store comes back from the append-only journal instead of raising
    on import.
    """
    store = open_store(tmp_path)
    store.add(make_span(text="порядок евакуації"), "sha")
    store.add(make_span(text="правила зберігання"), "sha")
    store.close()

    (tmp_path / "korpus.sqlite3").write_bytes(b"this is not a database" * 100)

    recovered = open_store(tmp_path)
    assert recovered.recovered is True
    assert recovered.count() == 2
    assert list(tmp_path.glob("korpus.corrupt-*"))
    assert recovered.healthy() is True


def test_recovery_skips_unreadable_journal_lines(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.add(make_span(), "sha")
    store.close()
    with (tmp_path / "corpus-journal.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json at all}\n")
        handle.write('{"chunk_id": "not-a-uuid"}\n')
    (tmp_path / "korpus.sqlite3").write_bytes(b"broken")

    recovered = open_store(tmp_path)
    assert recovered.recovered is True
    assert recovered.count() == 1


def test_health_reports_a_working_store(tmp_path: Path) -> None:
    assert open_store(tmp_path).healthy() is True


def test_concurrent_writers_do_not_collide(tmp_path: Path) -> None:
    """The server answers on a threadpool; one connection is shared under a lock."""
    store = open_store(tmp_path)
    errors: list[Exception] = []

    def write(index: int) -> None:
        try:
            store.add(make_span(text=f"фрагмент {index}"), "sha")
            store.record_audit("answer.completed", {"n": index})
        except Exception as error:  # noqa: BLE001 - the assertion is that none occur
            errors.append(error)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert store.count() == 16
    assert store.audit_count() == 16


def test_reading_from_another_thread_is_allowed(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.add(make_span(), "sha")
    result: list[int] = []

    def read() -> None:
        result.append(store.count())

    thread = threading.Thread(target=read)
    thread.start()
    thread.join()
    assert result == [1]


def test_the_journal_is_append_only(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.add(make_span(text="перший"), "sha")
    first = (tmp_path / "corpus-journal.jsonl").read_text(encoding="utf-8")
    store.add(make_span(text="другий"), "sha")
    second = (tmp_path / "corpus-journal.jsonl").read_text(encoding="utf-8")
    assert second.startswith(first)
    assert len(second.splitlines()) == 2


def test_integrity_failure_is_detected_rather_than_assumed(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.close()
    broken = CorpusStore.__new__(CorpusStore)
    broken._lock = threading.RLock()
    broken._connection = sqlite3.connect(":memory:")
    broken._connection.row_factory = sqlite3.Row
    broken._connection.close()
    assert broken.healthy() is False


def test_a_failed_integrity_check_is_raised_not_swallowed(tmp_path: Path) -> None:
    """The branch that decides a file is corrupt, exercised directly."""

    class DamagedConnection:
        def execute(self, *args: object) -> DamagedConnection:
            return self

        def fetchone(self) -> tuple[str, ...]:
            return ("*** in database main: page 3 is never used",)

    store = open_store(tmp_path)
    store._connection = DamagedConnection()  # type: ignore[assignment]
    assert store.healthy() is False


def test_an_empty_integrity_result_is_treated_as_failure(tmp_path: Path) -> None:
    class SilentConnection:
        def execute(self, *args: object) -> SilentConnection:
            return self

        def fetchone(self) -> None:
            return None

    store = open_store(tmp_path)
    store._connection = SilentConnection()  # type: ignore[assignment]
    assert store.healthy() is False


def test_replay_without_a_journal_restores_nothing(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.journal.unlink(missing_ok=True)
    assert store.replay_journal() == 0


def test_replay_ignores_blank_journal_lines(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.add(make_span(), "sha")
    with store.journal.open("a", encoding="utf-8") as handle:
        handle.write("\n   \n")
    fresh = CorpusStore(tmp_path / "second.sqlite3", journal=store.journal)
    assert fresh.replay_journal() == 1


def test_replay_is_idempotent_on_chunks_already_present(tmp_path: Path) -> None:
    """Replaying over a live database must not fail on rows that survived."""
    store = open_store(tmp_path)
    store.add(make_span(), "sha")
    assert store.replay_journal() == 0  # the row is already there
    assert store.count() == 1


def test_rebuild_works_when_the_file_vanished_entirely(tmp_path: Path) -> None:
    """A deleted database is the same problem as a corrupt one: rebuild, do not crash."""
    store = open_store(tmp_path)
    store.add(make_span(), "sha")
    store.close()
    (tmp_path / "korpus.sqlite3").unlink()

    revived = CorpusStore.__new__(CorpusStore)
    revived.path = tmp_path / "korpus.sqlite3"
    revived.journal = tmp_path / "corpus-journal.jsonl"
    revived.recovered = False
    revived._lock = threading.RLock()
    revived._quarantine_and_rebuild()
    assert revived.recovered is True
    assert revived.count() == 1
    assert not list(tmp_path.glob("korpus.corrupt-*"))
