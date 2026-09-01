from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.semantic import HttpEmbeddingProvider, PgVectorSemanticIndex

from apps.api.tests.helpers import StubSnapshotReader


class FakeResponse:
    def __init__(
        self, payload: object, *, status_code: int = 200, content: bytes | None = None
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = content if content is not None else json.dumps(payload).encode()

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http failure")

    def json(self) -> object:
        return self._payload


class FakeEmbeddingClient:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.closed = False
        self.posts: list[tuple[str, object]] = []

    def post(self, endpoint: str, json: object) -> FakeResponse:
        self.posts.append((endpoint, json))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def get(self, endpoint: str, headers: object) -> FakeResponse:
        del endpoint, headers
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def close(self) -> None:
        self.closed = True


def test_local_object_store_full_lifecycle_and_fail_closed_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        LocalObjectStore(tmp_path / "invalid", max_object_bytes=0)
    store = LocalObjectStore(tmp_path / "objects", max_object_bytes=64)
    content = b"authoritative text"
    digest = hashlib.sha256(content).hexdigest()
    key = store.put(content, digest, "ignored.txt")
    assert store.put(content, digest, "again.txt") == key
    assert store.exists(key)
    assert store.get(key) == content
    assert store.list_keys() == {key}
    destination = tmp_path / "download" / "source.txt"
    store.get_to_path(key, destination)
    assert destination.read_bytes() == content
    assert store.healthcheck() is True
    assert store.close() is None

    source = tmp_path / "source.bin"
    source.write_bytes(b"second")
    second_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    second_key = store.put_path(source, second_hash, "source.bin")
    assert store.put_path(source, second_hash, "source.bin") == second_key

    with pytest.raises(ValueError, match="invalid source hash"):
        store.put(b"x", "bad", "x")
    with pytest.raises(ValueError, match="does not match"):
        store.put(b"x", "a" * 64, "x")
    with pytest.raises(ValueError, match="invalid object key"):
        store.get("../escape")

    collision_path = store.root / key
    collision_path.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="collision"):
        store.put(content, digest, "x")
    with pytest.raises(RuntimeError, match="integrity"):
        store.get(key)

    oversized = tmp_path / "oversized"
    oversized.write_bytes(b"x" * 65)
    with pytest.raises(ValueError, match="size limit"):
        store.put_path(oversized, hashlib.sha256(oversized.read_bytes()).hexdigest(), "x")
    wrong = tmp_path / "wrong"
    wrong.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="does not match"):
        store.put_path(wrong, "b" * 64, "x")


def test_embedding_provider_normalization_validation_health_and_close() -> None:
    client = FakeEmbeddingClient(FakeResponse({"embedding": [3.0, 4.0, 0, 0, 0, 0, 0, 0]}))
    provider = HttpEmbeddingProvider("https://embed.example/v1", "model-v1", 8, client=client)
    vector = provider.embed("query")
    assert vector[:2] == [0.6, 0.8]
    assert provider.healthcheck() is True
    provider.close()
    assert client.closed
    with pytest.raises(ValueError, match="input length"):
        provider.embed("")

    cases = [
        ({"embedding": [1.0]}, "dimensions"),
        ({"embedding": [0.0] * 8}, "zero vector"),
        ({"embedding": [float("inf")] + [1.0] * 7}, "invalid vector"),
    ]
    for payload, message in cases:
        failing = HttpEmbeddingProvider(
            "https://embed.example/v1",
            "model-v1",
            8,
            client=FakeEmbeddingClient(FakeResponse(payload)),
        )
        with pytest.raises(RuntimeError, match=message):
            failing.embed("query")
    too_large = HttpEmbeddingProvider(
        "https://embed.example/v1",
        "model-v1",
        8,
        max_response_bytes=1024,
        client=FakeEmbeddingClient(FakeResponse({"embedding": [1.0] * 8}, content=b"x" * 1025)),
    )
    with pytest.raises(RuntimeError, match="response exceeds"):
        too_large.embed("query")
    unhealthy = HttpEmbeddingProvider(
        "https://embed.example/v1", "model-v1", 8, client=FakeEmbeddingClient(OSError("down"))
    )
    assert unhealthy.healthcheck() is False
    with pytest.raises(ValueError, match="resilience"):
        HttpEmbeddingProvider(
            "https://embed.example/v1", "model-v1", 8, max_attempts=0, client=client
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"embeddings": [[3.0, 4.0, 0, 0, 0, 0, 0, 0]]},
        {"data": [{"embedding": [3.0, 4.0, 0, 0, 0, 0, 0, 0]}]},
    ],
)
def test_embedding_provider_accepts_bounded_ollama_and_openai_envelopes(payload) -> None:
    provider = HttpEmbeddingProvider(
        "http://127.0.0.1:11434/api/embed",
        "model-v1",
        8,
        client=FakeEmbeddingClient(FakeResponse(payload)),
    )

    assert provider.embed("query")[:2] == [0.6, 0.8]


@pytest.mark.parametrize(
    "payload",
    [
        {"embeddings": []},
        {"embeddings": [[1.0] * 8, [1.0] * 8]},
        {"data": [{"embedding": [1.0] * 8}, {"embedding": [1.0] * 8}]},
        [1.0] * 8,
    ],
)
def test_embedding_provider_rejects_ambiguous_or_untyped_envelopes(payload) -> None:
    provider = HttpEmbeddingProvider(
        "https://embed.example/v1",
        "model-v1",
        8,
        client=FakeEmbeddingClient(FakeResponse(payload)),
    )

    with pytest.raises(RuntimeError, match="invalid batch cardinality"):
        provider.embed("query")


def test_embedding_batch_preserves_cardinality_order_and_normalizes() -> None:
    client = FakeEmbeddingClient(
        FakeResponse({"embeddings": [[3.0, 4.0] + [0.0] * 6, [0.0, 5.0] + [0.0] * 6]})
    )
    provider = HttpEmbeddingProvider(
        "http://127.0.0.1:11434/api/embed", "model-v1", 8, client=client
    )

    vectors = provider.embed_many(["first", "second"])

    assert vectors[0][:2] == [0.6, 0.8]
    assert vectors[1][:2] == [0.0, 1.0]
    assert client.posts == [
        (
            "http://127.0.0.1:11434/api/embed",
            {"model": "model-v1", "input": ["first", "second"]},
        )
    ]


def test_embedding_batch_fails_closed_on_count_and_configuration() -> None:
    provider = HttpEmbeddingProvider(
        "https://embed.example/v1",
        "model-v1",
        8,
        max_batch_size=2,
        client=FakeEmbeddingClient(FakeResponse({"embeddings": [[1.0] * 8]})),
    )
    with pytest.raises(ValueError, match="cardinality"):
        provider.embed_many([])
    with pytest.raises(ValueError, match="cardinality"):
        provider.embed_many(["a", "b", "c"])
    with pytest.raises(RuntimeError, match="batch cardinality"):
        provider.embed_many(["a", "b"])
    with pytest.raises(ValueError, match="must not exceed"):
        HttpEmbeddingProvider(
            "https://embed.example/v1", "model-v1", 8, max_batch_size=65, client=provider.client
        )


class FakeResult:
    def __init__(self, *, rows: list[object] | None = None, first: object | None = None) -> None:
        self._rows = rows or []
        self._first = first

    def all(self) -> list[object]:
        return self._rows

    def first(self) -> object | None:
        return self._first


class FakeConnection:
    def __init__(self, span_id: str, visible: bool = True) -> None:
        self.span_id = span_id
        self.visible = visible
        self.statements: list[str] = []

    def execute(self, statement: object, parameters: object | None = None) -> FakeResult:
        del parameters
        sql = str(statement)
        self.statements.append(sql)
        if "SELECT s.id AS span_id" in sql:
            return FakeResult(rows=[SimpleNamespace(span_id=self.span_id, score=0.75)])
        if "SELECT d.corpus_id" in sql:
            return FakeResult(first=SimpleNamespace(corpus_id="public") if self.visible else None)
        return FakeResult()


class BeginContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, *args: object) -> None:
        return None


class FakeEngine:
    def __init__(self, span_id: str, *, name: str = "postgresql", visible: bool = True) -> None:
        self.dialect = SimpleNamespace(name=name)
        self.connection = FakeConnection(span_id, visible=visible)

    def begin(self) -> BeginContext:
        return BeginContext(self.connection)


class Governance:
    def __init__(self) -> None:
        self.calls: list[frozenset[str]] = []

    def require_external_embedding(self, corpora: frozenset[str]) -> None:
        self.calls.append(corpora)


def test_pgvector_search_upsert_governance_and_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    # Прив'язку робить функція модуля, а не статичний метод класу: підклас із
    # межею RLS перевизначає МЕТОД, тож статичний виклик не міг би знати про брокера.
    monkeypatch.setattr(
        "korpus.infrastructure.repository.apply_session_claims",
        lambda connection, identity: None,
    )
    span_id = uuid4()
    provider = SimpleNamespace(
        model_id="m1",
        dimensions=8,
        embed=lambda text: [0.125] * 8,
        healthcheck=lambda: True,
        close=lambda: None,
    )
    governance = Governance()
    engine = FakeEngine(str(span_id))
    index = PgVectorSemanticIndex(engine, provider, corpus_governance=governance)
    identity = Identity(
        subject="u",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )
    denied = index.search(
        identity, "query", frozenset({"denied"}), __import__("datetime").date.today(), 5
    )
    assert denied == []
    result = index.search(
        identity, "query", frozenset({"public"}), __import__("datetime").date.today(), 5
    )
    assert result == [(span_id, 0.75)]
    index.upsert(identity, span_id, "text", hashlib.sha256(b"text").hexdigest())
    assert governance.calls == [frozenset({"public"}), frozenset({"public"})]
    assert index.healthcheck() is True
    index.close()
    assert any("INSERT INTO span_embeddings" in sql for sql in engine.connection.statements)

    hidden = PgVectorSemanticIndex(FakeEngine(str(span_id), visible=False), provider)
    with pytest.raises(PermissionError, match="not visible"):
        hidden.upsert(identity, span_id, "text", "a" * 64)
    with pytest.raises(ValueError, match="requires PostgreSQL"):
        PgVectorSemanticIndex(FakeEngine(str(span_id), name="sqlite"), provider)


def test_parser_worker_success_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from korpus.infrastructure import parser_worker
    from korpus.infrastructure.extraction import ExtractedPage

    request = {
        "path": str(tmp_path / "x.txt"),
        "filename": "x.txt",
        "mime_type": "text/plain",
        "ocr_enabled": False,
        "ocr_languages": "ukr",
        "max_pdf_pages": 10,
        "ocr_total_timeout_seconds": 5,
    }
    monkeypatch.setattr(
        parser_worker,
        "extract_pages_from_path",
        lambda *args, **kwargs: ([ExtractedPage(1, "ok")], "plain_text"),
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    assert parser_worker.main() == 0
    assert json.loads(output.getvalue())["pages"][0]["text"] == "ok"

    monkeypatch.setattr(sys, "stdin", io.StringIO("not-json"))
    error = io.StringIO()
    monkeypatch.setattr(sys, "stderr", error)
    assert parser_worker.main() == 2
    assert "parser error" in error.getvalue()


class DummyAuditVerification:
    def model_dump_json(self, indent: int = 2) -> str:
        del indent
        return '{"valid":true}'


class DummyRepository:
    def __init__(self) -> None:
        self.engine = object()
        self.closed = False
        self.initialized = False
        self.inventory = {"content": {"present", "missing"}, "quarantine": {"queued"}}

    def initialize(self, create_schema: bool) -> None:
        self.initialized = create_schema

    def verify_audit(self) -> DummyAuditVerification:
        return DummyAuditVerification()

    def object_inventory(self) -> dict[str, set[str]]:
        return self.inventory

    corpus_snapshot_reader = StubSnapshotReader("d" * 64)

    def close(self) -> None:
        self.closed = True


class DummyStore:
    def __init__(self, keys: set[str]) -> None:
        self.keys = keys
        self.closed = False

    def list_keys(self) -> set[str]:
        return self.keys

    def close(self) -> None:
        self.closed = True


def _cli_settings() -> SimpleNamespace:
    return SimpleNamespace(
        schema_mode="auto",
        dev_subject="dev-user",
        dev_roles="admin",
        dev_clearance="public",
        dev_corpora="public",
        dev_compartments="",
        ingestion_job_lease_seconds=30,
    )


def _run_cli(
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
    *,
    content: set[str] | None = None,
    quarantine: set[str] | None = None,
):
    from korpus import cli

    repository = DummyRepository()
    content_store = DummyStore(content if content is not None else {"present", "missing"})
    quarantine_store = DummyStore(quarantine if quarantine is not None else {"queued"})
    monkeypatch.setattr(cli, "get_settings", _cli_settings)
    monkeypatch.setattr(cli, "create_repository", lambda settings, policy: repository)
    monkeypatch.setattr(cli, "create_object_store", lambda settings: content_store)
    monkeypatch.setattr(cli, "create_quarantine_store", lambda settings: quarantine_store)
    monkeypatch.setattr(sys, "argv", ["korpus", *command])
    return cli, repository, content_store, quarantine_store


def test_cli_read_commands_close_all_resources(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli, repository, content, quarantine = _run_cli(monkeypatch, ["init-db"])
    cli.main()
    assert "database initialized" in capsys.readouterr().out
    assert repository.initialized and repository.closed and content.closed and quarantine.closed

    cli, repository, content, quarantine = _run_cli(monkeypatch, ["verify-audit"])
    cli.main()
    assert '"valid":true' in capsys.readouterr().out
    assert repository.closed and content.closed and quarantine.closed

    cli, repository, content, quarantine = _run_cli(monkeypatch, ["release-id"])
    cli.main()
    assert capsys.readouterr().out.strip() == "d" * 64
    assert repository.closed and content.closed and quarantine.closed

    cli, repository, content, quarantine = _run_cli(monkeypatch, ["issue-token"])
    monkeypatch.setattr(cli, "issue_token", lambda identity, settings: "signed-token")
    cli.main()
    assert capsys.readouterr().out.strip() == "signed-token"
    assert repository.closed and content.closed and quarantine.closed


def test_cli_reconciliation_and_worker_boundaries(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli, repository, content, quarantine = _run_cli(
        monkeypatch,
        ["reconcile-objects"],
        content={"present", "missing", "orphan"},
        quarantine={"queued", "orphan-q"},
    )
    cli.main()
    report = json.loads(capsys.readouterr().out)
    assert report["content_orphaned"] == ["orphan"]
    assert report["quarantine_orphaned"] == ["orphan-q"]
    assert repository.closed and content.closed and quarantine.closed

    cli, repository, content, quarantine = _run_cli(
        monkeypatch, ["reconcile-objects"], content={"present"}, quarantine=set()
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    capsys.readouterr()
    assert repository.closed and content.closed and quarantine.closed

    class Queue:
        def __init__(self, engine: object) -> None:
            self.engine = engine

    class Worker:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def run_once(self) -> SimpleNamespace:
            return SimpleNamespace(job=None, claimed=False)

    cli, repository, content, quarantine = _run_cli(
        monkeypatch, ["worker-once", "--worker-id", "w1"]
    )
    monkeypatch.setattr(cli, "SqlIngestionJobQueue", Queue)
    monkeypatch.setattr(cli, "IngestionWorker", Worker)
    monkeypatch.setattr(cli, "_ingestion_service", lambda *args: object())
    cli.main()
    assert capsys.readouterr().out.strip() == "no queued job"
    assert repository.closed and content.closed and quarantine.closed

    cli, repository, content, quarantine = _run_cli(
        monkeypatch, ["worker-loop", "--idle-seconds", "0"]
    )
    monkeypatch.setattr(cli, "SqlIngestionJobQueue", Queue)
    monkeypatch.setattr(cli, "IngestionWorker", Worker)
    monkeypatch.setattr(cli, "_ingestion_service", lambda *args: object())
    with pytest.raises(SystemExit, match="idle-seconds"):
        cli.main()
    assert repository.closed and content.closed and quarantine.closed

    monkeypatch.delenv("KORPUS_WORKER_ID", raising=False)
    assert cli._worker_id("explicit") == "explicit"
    monkeypatch.setenv("KORPUS_WORKER_ID", "environment")
    assert cli._worker_id(None) == "environment"


class ClosingBody(io.BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.was_closed = False

    def close(self) -> None:
        self.was_closed = True
        super().close()


class PaginatedS3:
    def __init__(self) -> None:
        self.closed = False
        self.calls = 0

    def head_object(self, **kwargs: object) -> object:
        del kwargs
        error = RuntimeError("missing")
        error.response = {"Error": {"Code": "404"}}  # type: ignore[attr-defined]
        raise error

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        del kwargs
        self.calls += 1
        if self.calls == 1:
            return {
                "Contents": [{"Key": "objects/aa/bb/" + "a" * 64}],
                "IsTruncated": True,
                "NextContinuationToken": "n",
            }
        return {"Contents": [{"Key": "objects/cc/dd/" + "c" * 64}], "IsTruncated": False}

    def close(self) -> None:
        self.closed = True


def test_s3_path_download_inventory_and_cleanup(tmp_path: Path) -> None:
    client = PaginatedS3()
    object_store = __import__("korpus.infrastructure.object_store", fromlist=["S3ObjectStore"])
    store = object_store.S3ObjectStore(bucket="bucket", prefix="objects", client=client)
    content = b"downloaded"
    digest = hashlib.sha256(content).hexdigest()
    key = f"objects/{digest[:2]}/{digest[2:4]}/{digest}"
    body = ClosingBody(content)
    client.get_object = lambda **kwargs: {
        "Body": body,
        "Metadata": {"sha256": digest},
        "ContentLength": len(content),
    }
    destination = tmp_path / "target" / "file"
    store.get_to_path(key, destination)
    assert destination.read_bytes() == content
    assert body.was_closed
    keys = store.list_keys()
    assert len(keys) == 2
    assert store.exists(key) is False
    store.close()
    assert client.closed

    client.calls = 0
    client.list_objects_v2 = lambda **kwargs: {"IsTruncated": True}
    with pytest.raises(RuntimeError, match="continuation token"):
        store.list_keys()
