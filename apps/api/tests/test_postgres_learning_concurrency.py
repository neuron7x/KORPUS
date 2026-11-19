"""Actual PostgreSQL actors must serialize neutral graph edits with publication."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from queue import Queue
from threading import Barrier, get_ident
from time import monotonic

import pytest
from korpus.domain.learning import CoursePublication, CoursePublicationState, CourseVersion
from korpus.infrastructure import learning_publication
from korpus.infrastructure.learning_version_reader import load_course_version
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from apps.api.tests.learning_postgres_support import LearningPostgres, course_graph
from apps.api.tests.learning_postgres_support import learning_postgres as learning_postgres
from apps.api.tests.test_learning_competency_integrity import CompetencyStore, _statement
from apps.api.tests.test_learning_competency_integrity import (
    competency_store as competency_store,
)
from apps.api.tests.test_postgres_learning_persistence import CONTENT_UPDATES

pytestmark = [pytest.mark.postgres, pytest.mark.concurrency]

_WAIT_SECONDS = 5
_COMPETENCY_EDITS = ("insert", "update", "delete", "move-out", "move-in")
_EDITS = (*CONTENT_UPDATES, *(f"competency:{operation}" for operation in _COMPETENCY_EDITS))


def _session(connection: Connection) -> int:
    assert connection.dialect.name == "postgresql"
    assert connection.exec_driver_sql("SHOW transaction_isolation").scalar_one() == "read committed"
    connection.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
    connection.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
    return int(connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one())


@dataclass
class _ActorBarrier:
    ready: Queue[int] = field(default_factory=Queue)
    start: Barrier = field(default_factory=lambda: Barrier(2, timeout=_WAIT_SECONDS))

    def enter(self, connection: Connection) -> None:
        self.ready.put(_session(connection))
        self.start.wait()

    def release(self) -> int:
        pid = self.ready.get(timeout=_WAIT_SECONDS)
        self.start.wait()
        return pid


def _wait_for_parent_lock(
    holder: Connection, waiting_pid: int, holder_pid: int, future: Future[object]
) -> None:
    deadline = monotonic() + _WAIT_SECONDS
    while monotonic() < deadline:
        if future.done():
            raise AssertionError(
                "competing operation completed before the parent owner committed: "
                f"{future.exception()!r}"
            )
        blockers = holder.execute(
            text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting_pid}
        ).scalar_one()
        if holder_pid in blockers:
            return
        # This only yields between observations. The server's blocker identity,
        # never elapsed time or an unfinished Future, establishes serialization.
        wait((future,), timeout=0.01)
    raise AssertionError("PostgreSQL did not report the parent owner as the blocker")


def _edit_statement(store: CompetencyStore, case: str) -> tuple[str, dict[str, str]]:
    if case.startswith("competency:"):
        return _statement(store, case.removeprefix("competency:"))
    key = "id" if case in {"learning_courses", "learning_course_versions"} else "course_version_id"
    identifier = store.graph.course_id if case == "learning_courses" else store.graph.id
    return (
        f"UPDATE {case} SET {CONTENT_UPDATES[case]} WHERE {key}=:identifier",
        {"identifier": identifier},
    )


def _edit(
    store: CompetencyStore, actor: _ActorBarrier, statement: str, parameters: dict[str, str]
) -> int:
    with store.engine.begin() as connection:
        actor.enter(connection)
        return connection.execute(text(statement), parameters).rowcount


def _publish(store: CompetencyStore, actor: _ActorBarrier) -> CoursePublication:
    worker = get_ident()

    def begin(connection: Connection) -> None:
        if get_ident() == worker:
            actor.enter(connection)

    event.listen(store.engine, "begin", begin)
    try:
        return store.learning.publish_version(
            store.graph.id,
            reviewed_by="concurrent-library-reviewer",
            as_of=store.today,
            identity=store.identity,
        )
    finally:
        event.remove(store.engine, "begin", begin)


@pytest.mark.parametrize("case", _EDITS)
@pytest.mark.parametrize("competency_store", ["postgres"], indirect=True)
def test_postgres_publication_blocks_content_until_immutable_state_is_visible(
    competency_store: CompetencyStore, case: str
) -> None:
    store = competency_store
    statement, parameters = _edit_statement(store, case)
    before_course = store.learning.get_course(store.graph.course_id)
    # Each adversarial statement is valid draft DML; a foreign-key or privilege
    # refusal must not be mistaken for the immutable-history guard.
    with store.engine.connect() as control:
        transaction = control.begin()
        assert control.execute(text(statement), parameters).rowcount > 0
        transaction.rollback()
    actor = _ActorBarrier()
    with store.engine.connect() as publisher, ThreadPoolExecutor(max_workers=1) as executor:
        transaction = publisher.begin()
        try:
            publisher_pid = _session(publisher)
            store.learning._sources.bind(publisher, store.identity)
            result = publisher.execute(
                text(
                    "UPDATE learning_publications SET state='published', "
                    "reviewed_at=CURRENT_TIMESTAMP, reviewed_by='concurrent-library-reviewer' "
                    "WHERE course_version_id=:version"
                ),
                {"version": store.graph.id},
            )
            assert result.rowcount == 1
            future = executor.submit(_edit, store, actor, statement, parameters)
            editor_pid = actor.release()
            _wait_for_parent_lock(publisher, editor_pid, publisher_pid, future)
            transaction.commit()
            with pytest.raises(DBAPIError, match="immutable") as failure:
                future.result(timeout=15)
            assert getattr(failure.value.orig, "sqlstate", None) == "42501"
        finally:
            actor.start.abort()
            if transaction.is_active:
                transaction.rollback()
    publication = store.learning.get_publication(store.graph.id)
    assert publication is not None and publication.state is CoursePublicationState.PUBLISHED
    assert publication.reviewed_by == "concurrent-library-reviewer"
    assert store.learning.get_version(store.graph.id) == store.graph
    assert store.learning.get_version(store.draft.id) == store.draft
    assert store.learning.get_course(store.graph.course_id) == before_course


@pytest.mark.parametrize("competency_store", ["postgres"], indirect=True)
def test_postgres_draft_edit_commits_before_publication_reads_and_validates_graph(
    competency_store: CompetencyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = competency_store
    statement, parameters = _statement(store, "update")
    observed: Queue[CourseVersion | None] = Queue()
    original_reader = learning_publication.load_course_version

    def read(connection: Connection, version_id: str) -> CourseVersion | None:
        graph = original_reader(connection, version_id)
        observed.put(graph)
        return graph

    monkeypatch.setattr(learning_publication, "load_course_version", read)
    actor = _ActorBarrier()
    with store.engine.connect() as editor, ThreadPoolExecutor(max_workers=1) as executor:
        transaction = editor.begin()
        try:
            editor_pid = _session(editor)
            assert editor.execute(text(statement), parameters).rowcount == 1
            expected = load_course_version(editor, store.graph.id)
            assert expected is not None and expected != store.graph
            future = executor.submit(_publish, store, actor)
            publisher_pid = actor.release()
            _wait_for_parent_lock(editor, publisher_pid, editor_pid, future)
            assert observed.empty(), "publication read the graph before owning its lifecycle"
            transaction.commit()
            publication = future.result(timeout=15)
        finally:
            actor.start.abort()
            if transaction.is_active:
                transaction.rollback()
    assert publication.state is CoursePublicationState.PUBLISHED
    assert observed.get_nowait() == expected
    assert observed.empty()
    assert store.learning.get_version(store.graph.id) == expected
    assert store.learning.get_version(store.draft.id) == store.draft
    with (
        pytest.raises(DBAPIError, match="immutable") as failure,
        store.engine.begin() as connection,
    ):
        connection.execute(text(_statement(store, "delete")[0]), parameters)
    assert getattr(failure.value.orig, "sqlstate", None) == "42501"
    assert store.learning.get_version(store.graph.id) == expected


def _create_first_version(
    store: LearningPostgres, graph: CourseVersion, actor: _ActorBarrier, path: str
) -> None:
    worker = get_ident()

    def begin(connection: Connection) -> None:
        if get_ident() == worker:
            actor.enter(connection)

    event.listen(store.app, "begin", begin)
    try:
        if path == "repository":
            store.learning.create_version(graph)
        else:
            # Bypass the Python writer. Roll back this deliberately incomplete
            # INSERT after observing the database trigger's course-parent lock.
            with store.app.connect() as connection:
                transaction = connection.begin()
                assert (
                    connection.execute(
                        text(
                            "INSERT INTO learning_course_versions "
                            "(id,course_id,revision,created_at) "
                            "VALUES (:id,:course,:revision,CURRENT_TIMESTAMP)"
                        ),
                        {"id": graph.id, "course": graph.course_id, "revision": graph.revision},
                    ).rowcount
                    == 1
                )
                transaction.rollback()
    finally:
        event.remove(store.app, "begin", begin)


@pytest.mark.parametrize("path", ["repository", "sql"])
def test_postgres_first_version_waits_for_course_identity_edit(
    learning_postgres: LearningPostgres, path: str
) -> None:
    store = learning_postgres
    graph = course_graph()
    actor = _ActorBarrier()
    with store.app.connect() as editor, ThreadPoolExecutor(max_workers=1) as executor:
        transaction = editor.begin()
        try:
            editor_pid = _session(editor)
            for table in ("learning_course_versions", "learning_publications"):
                assert editor.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
            assert (
                editor.execute(
                    text("UPDATE learning_courses SET title='Revised library title' WHERE id=:id"),
                    {"id": graph.course_id},
                ).rowcount
                == 1
            )
            future = executor.submit(_create_first_version, store, graph, actor, path)
            creator_pid = actor.release()
            _wait_for_parent_lock(editor, creator_pid, editor_pid, future)
            transaction.commit()
            future.result(timeout=15)
        finally:
            actor.start.abort()
            if transaction.is_active:
                transaction.rollback()
    if path == "sql":
        assert store.learning.get_version(graph.id) is None
        store.learning.create_version(graph)
    assert store.learning.get_version(graph.id) == graph
    publication = store.learning.publish_version(
        graph.id,
        reviewed_by="concurrent-library-reviewer",
        as_of=store.today,
        identity=store.identity,
    )
    assert publication.state is CoursePublicationState.PUBLISHED
    published_course = store.learning.get_course(graph.course_id)
    assert published_course is not None and published_course.title == "Revised library title"
    with pytest.raises(DBAPIError, match="immutable") as failure, store.app.begin() as connection:
        connection.execute(
            text("UPDATE learning_courses SET title='Late title' WHERE id=:id"),
            {"id": graph.course_id},
        )
    assert getattr(failure.value.orig, "sqlstate", None) == "42501"
    assert store.learning.get_course(graph.course_id) == published_course
    assert store.learning.get_version(graph.id) == graph
