"""Finite native reader/writer actors; no database or role observations are stubbed."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Barrier, Event, Lock, get_ident
from uuid import UUID

from korpus.domain.models import ReviewState
from korpus.infrastructure.review_transitions import transition_version_in_connection
from sqlalchemy import event, text

TIMEOUT = 8
_ACTOR: ContextVar[tuple[object, str] | None] = ContextVar("native_snapshot_actor", default=None)


def approve_in_connection(connection, repository, actor, version_id):
    record, _anchor = transition_version_in_connection(
        connection,
        actor=actor,
        version_id=UUID(version_id),
        expected_state=ReviewState.CONTENT_REVIEWED,
        target_state=ReviewState.APPROVED,
        note="neutral competing writer approval",
        acknowledge_near_duplicate=True,
        acknowledge_extraction_quality=True,
        reviewer_credential_id=None,
        access_tier=None,
        version_mapper=repository._version,
        document_mapper=repository._document,
        append_audit=repository.audit_in_connection,
    )
    assert record.review_state is ReviewState.APPROVED


class NativeActors:
    def __init__(self, repository, writer_identity, mutation, *, review_writer=False):
        self.repository = repository
        self.writer_identity = writer_identity
        self.mutation = mutation
        self.writer_engine = (
            repository.review_engine or repository.engine if review_writer else repository.engine
        )
        self.engines = tuple({repository.engine, self.writer_engine})
        self.barrier = Barrier(2, timeout=TIMEOUT)
        self.ready = Event()
        self.committed = Event()
        self.reader_finished = Event()
        self.writer_thread = None
        self.active = {}
        self.principals = {"reader": {}, "writer": {}}
        self.references = []
        self.inspecting = set()
        self.lock = Lock()
        self.pauses = 0
        self.completed_commit = False
        self.open_reader_connections_at_pause = None
        self.unscoped_checkouts = 0

    def _actor(self):
        active = _ACTOR.get()
        return active[1] if active is not None and active[0] is self else None

    def _checkout(self, connection, record, _proxy):
        with self.lock:
            if self._actor() is None:
                self.unscoped_checkouts += 1
                return
            self.active[id(record)] = get_ident()
            self.references.append(connection)

    def _checkin(self, _connection, record):
        with self.lock:
            self.active.pop(id(record), None)

    def _observe_sql(self, connection, _cursor, _statement, _parameters, _context, _many):
        actor = self._actor()
        if actor is None:
            return
        raw = connection.connection.driver_connection
        marker = id(raw)
        if marker in self.principals[actor] or marker in self.inspecting:
            return
        self.inspecting.add(marker)
        try:
            if connection.dialect.name == "postgresql":
                principal = dict(
                    connection.execute(
                        text(
                            "SELECT pg_backend_pid() AS backend_pid, current_user, session_user, "
                            "rolsuper, rolbypassrls, pg_has_role(current_user, "
                            "(SELECT relowner FROM pg_class WHERE oid='public.documents'::regclass), "
                            "'MEMBER') AS owner_member FROM pg_roles WHERE rolname=current_user"
                        )
                    )
                    .mappings()
                    .one()
                )
                expected = self.writer_engine if actor == "writer" else self.repository.engine
                assert (
                    principal["current_user"] == principal["session_user"] == expected.url.username
                )
                assert not principal["rolsuper"] and not principal["rolbypassrls"]
                assert not principal["owner_member"]
            else:
                assert connection.dialect.name == "sqlite"
                principal = {"connection_identity": marker, "role_model": "SQLite has no DB roles"}
            self.principals[actor][marker] = principal
        finally:
            self.inspecting.remove(marker)

    def pause_reader(self):
        assert self.ready.wait(TIMEOUT), "writer connection was not established"
        self.pauses += 1
        with self.lock:
            open_readers = [owner for owner in self.active.values() if owner != self.writer_thread]
        self.open_reader_connections_at_pause = len(open_readers)
        assert not open_readers, "reader retained a DB connection across the external boundary"
        self.barrier.wait()
        assert self.committed.wait(TIMEOUT), "writer did not commit before reader resumed"
        assert self.completed_commit, "writer failed before commit"

    def _write(self):
        context = _ACTOR.set((self, "writer"))
        self.writer_thread = get_ident()
        try:
            with self.writer_engine.connect() as connection:
                self.repository._apply_postgres_identity(connection, self.writer_identity)
                if connection.dialect.name == "postgresql":
                    connection.execute(text("SET LOCAL statement_timeout = '5s'"))
                    connection.execute(text("SET LOCAL lock_timeout = '3s'"))
                self.ready.set()
                self.barrier.wait()
                self.mutation(connection)
                connection.commit()
                assert not connection.in_transaction()
                self.completed_commit = True
                self.committed.set()
                # Keep this physical connection reserved until the reader finishes.
                # No database transaction remains open during this wait.
                assert self.reader_finished.wait(TIMEOUT), "reader did not finish after commit"
        finally:
            self.ready.set()
            self.committed.set()
            _ACTOR.reset(context)

    def run(self, action):
        def read():
            context = _ACTOR.set((self, "reader"))
            try:
                return action()
            finally:
                self.reader_finished.set()
                _ACTOR.reset(context)

        listeners = (
            ("checkout", self._checkout),
            ("checkin", self._checkin),
            ("before_cursor_execute", self._observe_sql),
        )
        for engine in self.engines:
            for name, function in listeners:
                event.listen(engine, name, function)
        try:
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="native-snapshot") as pool:
                writer = pool.submit(self._write)
                assert self.ready.wait(TIMEOUT)
                reader = pool.submit(read)
                try:
                    reader_failure = reader.exception(timeout=TIMEOUT * 3)
                finally:
                    self.reader_finished.set()
                    self.barrier.abort()
                writer_failure = writer.exception(timeout=TIMEOUT * 3)
                failures = [
                    error for error in (reader_failure, writer_failure) if error is not None
                ]
                if failures:
                    raise BaseExceptionGroup("native snapshot actors failed", failures)
                result = reader.result(timeout=0)
        finally:
            for engine in self.engines:
                for name, function in listeners:
                    event.remove(engine, name, function)
        assert self.completed_commit and self.pauses == 1
        assert self.principals["reader"] and self.principals["writer"]
        reader_ids, writer_ids = set(self.principals["reader"]), set(self.principals["writer"])
        assert reader_ids.isdisjoint(writer_ids)
        if self.repository.engine.dialect.name == "postgresql":
            reader_pids = {row["backend_pid"] for row in self.principals["reader"].values()}
            writer_pids = {row["backend_pid"] for row in self.principals["writer"].values()}
            assert reader_pids.isdisjoint(writer_pids)
        assert not self.active
        return result

    def observation(self):
        return {
            "dialect": self.repository.engine.dialect.name,
            "writer_committed": self.completed_commit,
            "barrier_releases": self.pauses,
            "reader_connections_open_at_barrier": self.open_reader_connections_at_pause,
            "unscoped_pool_checkouts": self.unscoped_checkouts,
            "principals": {name: list(values.values()) for name, values in self.principals.items()},
            "postgresql_observed": self.repository.engine.dialect.name == "postgresql",
        }
