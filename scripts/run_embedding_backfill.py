#!/usr/bin/env python3
"""Run bounded PostgreSQL embedding reconciliation and emit an atomic receipt."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.embedding_backfill_run import run_backfill  # noqa: E402
from korpus.config import Settings  # noqa: E402
from korpus.domain.models import AccessTier, Identity  # noqa: E402
from korpus.infrastructure.embedding_backfill import PgVectorEmbeddingBackfill  # noqa: E402
from korpus.infrastructure.embedding_provider import HttpEmbeddingProvider  # noqa: E402
from korpus.security.corpus_governance import CorpusGovernanceProfile  # noqa: E402


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, delete=False, encoding="utf-8"
        ) as out:
            temporary = Path(out.name)
            json.dump(payload, out, ensure_ascii=False, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _report(path: Path, payload: dict[str, object]) -> None:
    _atomic_json(path, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _configured(settings: Settings) -> tuple[str, str, Path, str] | None:
    values = (
        settings.embedding_endpoint,
        settings.embedding_model_id,
        settings.corpus_governance_profile_path,
        settings.corpus_governance_profile_sha256,
    )
    if any(value is None for value in values):
        return None
    endpoint, model_id, profile_path, profile_sha256 = values
    return str(endpoint), str(model_id), Path(profile_path), str(profile_sha256)


def _execute(args: argparse.Namespace, settings: Settings) -> int:
    configured = _configured(settings)
    if configured is None:
        required = {
            "embedding_endpoint": settings.embedding_endpoint,
            "embedding_model_id": settings.embedding_model_id,
            "corpus_governance_profile_path": settings.corpus_governance_profile_path,
            "corpus_governance_profile_sha256": settings.corpus_governance_profile_sha256,
        }
        missing = sorted(name for name, value in required.items() if value is None)
        _report(
            args.out,
            {
                "schema": "korpus.embedding-backfill-run.v1",
                "status": "CONFIGURATION_ERROR",
                "missing": missing,
                "promotion_authorized": False,
            },
        )
        return 2
    endpoint, model_id, profile_path, profile_sha256 = configured
    profile = CorpusGovernanceProfile.load(profile_path, profile_sha256)
    with ExitStack() as resources:
        provider = HttpEmbeddingProvider(
            endpoint,
            model_id,
            settings.embedding_dimensions,
            token=settings.resolved_embedding_token,
            timeout_seconds=settings.embedding_timeout_seconds,
            max_attempts=settings.embedding_max_attempts,
            max_response_bytes=settings.embedding_max_response_bytes,
            max_batch_size=args.batch_size,
        )
        resources.callback(provider.close)
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        resources.callback(engine.dispose)
        identity = Identity(
            subject="embedding-backfill",
            roles=frozenset({"admin", "curator"}),
            clearance=AccessTier.RESTRICTED,
            corpora=frozenset(profile.corpora),
        )
        worker = PgVectorEmbeddingBackfill(
            engine, provider, batch_size=args.batch_size, corpus_governance=profile
        )
        receipt = run_backfill(
            worker, identity, model_id=provider.model_id, max_batches=args.max_batches
        )
        report = {
            **receipt.as_dict(),
            "governance_profile_id": profile.profile_id,
            "governance_profile_sha256": profile_sha256,
            "embedding_dimensions": provider.dimensions,
            "batch_size": args.batch_size,
            "max_batches": args.max_batches,
        }
        _report(args.out, report)
        return 0 if receipt.complete else 3


def _positive_bounded(value: str, *, maximum: int, label: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > maximum:
        raise argparse.ArgumentTypeError(f"{label} must be between 1 and {maximum}")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--batch-size",
        type=lambda value: _positive_bounded(value, maximum=64, label="batch-size"),
        default=32,
    )
    parser.add_argument(
        "--max-batches",
        type=lambda value: _positive_bounded(value, maximum=10_000, label="max-batches"),
        default=100,
    )
    parser.add_argument("--out", type=Path, default=ROOT / "var/embedding-backfill-run.json")
    args = parser.parse_args()
    try:
        return _execute(args, Settings())
    except Exception as error:  # noqa: BLE001 - CLI boundary must leave a failure receipt.
        report = {
            "schema": "korpus.embedding-backfill-run.v1",
            "status": "EXECUTION_ERROR",
            "error_type": type(error).__name__,
            "promotion_authorized": False,
        }
        _report(args.out, report)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
