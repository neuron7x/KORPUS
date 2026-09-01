from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from korpus.application.embedding_backfill_run import BackfillRunReceipt
from korpus.application.embedding_coverage import assess_embedding_coverage

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "run_embedding_backfill_under_test", ROOT / "scripts/run_embedding_backfill.py"
)
assert SPEC is not None and SPEC.loader is not None
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "embedding_endpoint": "https://embedding.example.test/v1/embeddings",
        "embedding_model_id": "model-v1",
        "embedding_dimensions": 8,
        "embedding_timeout_seconds": 2.0,
        "embedding_max_attempts": 2,
        "embedding_max_response_bytes": 4096,
        "resolved_embedding_token": "secret",
        "database_url": "postgresql+psycopg://worker@db/korpus",
        "corpus_governance_profile_path": Path("governance.json"),
        "corpus_governance_profile_sha256": "a" * 64,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_missing_configuration_fails_closed_before_external_components(
    tmp_path: Path, monkeypatch
) -> None:
    out = tmp_path / "receipt.json"
    monkeypatch.setattr(
        cli,
        "HttpEmbeddingProvider",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider created")),
    )

    status = cli._execute(
        argparse.Namespace(out=out, batch_size=32, max_batches=10),
        _settings(embedding_endpoint=None, corpus_governance_profile_sha256=None),
    )

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert status == 2
    assert receipt["status"] == "CONFIGURATION_ERROR"
    assert receipt["promotion_authorized"] is False
    assert receipt["missing"] == [
        "corpus_governance_profile_sha256",
        "embedding_endpoint",
    ]


def test_component_boundary_binds_governance_and_closes_resources(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []
    profile = SimpleNamespace(profile_id="governed-v1", corpora={"doctrine"})
    monkeypatch.setattr(cli.CorpusGovernanceProfile, "load", lambda path, digest: profile)

    class Provider:
        model_id = "model-v1"
        dimensions = 8

        def __init__(self, *args: object, **kwargs: object) -> None:
            events.append("provider-open")

        def close(self) -> None:
            events.append("provider-close")

    class Engine:
        def dispose(self) -> None:
            events.append("engine-close")

    class Repository:
        """Скрипт більше не відкриває голий engine: під межею RLS особистість кладе
        брокер, і прив'язка живе в репозиторії."""

        engine = Engine()

        def close(self) -> None:
            events.append("engine-close")

        @staticmethod
        def _apply_postgres_identity(connection: object, identity: object) -> None:
            del connection, identity

    monkeypatch.setattr(cli, "HttpEmbeddingProvider", Provider)
    monkeypatch.setattr(cli, "create_repository", lambda *args, **kwargs: Repository())
    monkeypatch.setattr(cli, "exclusive_backfill_run", lambda *args: nullcontext())
    monkeypatch.setattr(cli, "PgVectorEmbeddingBackfill", lambda *args, **kwargs: object())
    coverage = assess_embedding_coverage(
        active_model_id="model-v1",
        active_dimensions=8,
        spans_total=8,
        spans_embedded_active=8,
        spans_embedded_other_model=0,
        spans_stale_text=0,
    )
    monkeypatch.setattr(
        cli,
        "PgVectorSemanticIndex",
        lambda *args, **kwargs: SimpleNamespace(
            coverage=lambda *args: coverage,
            ensure_index=lambda: "ix_span_embedding_hnsw_verified",
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_backfill",
        lambda *args, **kwargs: BackfillRunReceipt(
            model_id="model-v1",
            batches_executed=2,
            spans_selected=8,
            vectors_written=8,
            stale_during_write=0,
            complete=True,
            batch_budget_exhausted=False,
            duration_seconds=0.5,
        ),
    )
    out = tmp_path / "receipt.json"

    status = cli._execute(argparse.Namespace(out=out, batch_size=8, max_batches=2), _settings())

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert status == 0
    assert receipt["status"] == "COMPLETE"
    assert receipt["governance_profile_id"] == "governed-v1"
    assert receipt["governance_profile_sha256"] == "a" * 64
    assert receipt["embedding_dimensions"] == 8
    assert receipt["hnsw_index"] == "ix_span_embedding_hnsw_verified"
    digest = receipt.pop("receipt_sha256")
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert digest == hashlib.sha256(canonical.encode()).hexdigest()
    assert receipt["coverage"]["coverage_ratio"] == 1.0
    assert receipt["promotion_authorized"] is False
    assert events == ["provider-open", "engine-close", "provider-close"]


def test_incomplete_coverage_never_builds_index(tmp_path: Path, monkeypatch) -> None:
    profile = SimpleNamespace(profile_id="governed-v1", corpora={"doctrine"})
    monkeypatch.setattr(cli.CorpusGovernanceProfile, "load", lambda *args: profile)
    provider = SimpleNamespace(model_id="model-v1", dimensions=8, close=lambda: None)
    repository = SimpleNamespace(
        engine=SimpleNamespace(dispose=lambda: None),
        close=lambda: None,
        _apply_postgres_identity=lambda connection, identity: None,
    )
    monkeypatch.setattr(cli, "HttpEmbeddingProvider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(cli, "create_repository", lambda *args, **kwargs: repository)
    monkeypatch.setattr(cli, "exclusive_backfill_run", lambda *args: nullcontext())
    monkeypatch.setattr(cli, "PgVectorEmbeddingBackfill", lambda *args, **kwargs: object())
    coverage = assess_embedding_coverage(
        active_model_id="model-v1",
        active_dimensions=8,
        spans_total=8,
        spans_embedded_active=7,
        spans_embedded_other_model=0,
        spans_stale_text=0,
    )
    index_created = False

    def fail_index() -> str:
        nonlocal index_created
        index_created = True
        return "forbidden"

    monkeypatch.setattr(
        cli,
        "PgVectorSemanticIndex",
        lambda *args, **kwargs: SimpleNamespace(
            coverage=lambda *args: coverage, ensure_index=fail_index
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_backfill",
        lambda *args, **kwargs: BackfillRunReceipt(
            model_id="model-v1",
            batches_executed=1,
            spans_selected=7,
            vectors_written=7,
            stale_during_write=0,
            complete=False,
            batch_budget_exhausted=True,
            duration_seconds=0.1,
        ),
    )
    out = tmp_path / "receipt.json"

    status = cli._execute(argparse.Namespace(out=out, batch_size=8, max_batches=1), _settings())

    assert status == 3
    assert index_created is False
    assert json.loads(out.read_text())["hnsw_index"] is None


def test_atomic_receipt_replaces_previous_document(tmp_path: Path) -> None:
    out = tmp_path / "receipt.json"
    out.write_text("partial", encoding="utf-8")

    cli._atomic_json(out, {"status": "COMPLETE"})

    assert json.loads(out.read_text(encoding="utf-8")) == {"status": "COMPLETE"}
    assert list(tmp_path.iterdir()) == [out]


def test_cli_error_receipt_is_sanitized(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "error.json"
    monkeypatch.setattr(cli, "Settings", lambda: (_ for _ in ()).throw(RuntimeError("secret")))
    monkeypatch.setattr(cli.sys, "argv", ["run_embedding_backfill.py", "--out", str(out)])

    status = cli.main()

    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert status == 4
    assert receipt == {
        "schema": "korpus.embedding-backfill-run.v1",
        "status": "EXECUTION_ERROR",
        "error_type": "RuntimeError",
        "promotion_authorized": False,
    }
    assert "secret" not in out.read_text(encoding="utf-8")


def test_numeric_cli_contracts_are_bounded() -> None:
    assert cli._positive_bounded("64", maximum=64, label="batch-size") == 64
    for value in ("0", "65"):
        try:
            cli._positive_bounded(value, maximum=64, label="batch-size")
        except argparse.ArgumentTypeError:
            pass
        else:
            raise AssertionError("out-of-contract batch size was accepted")
