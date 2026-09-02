from __future__ import annotations

import argparse
import os
import socket
from datetime import UTC, datetime

from korpus.application.corpus_snapshot import release_token
from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.ingestion_jobs import IngestionWorker
from korpus.application.policy import PolicyEngine
from korpus.application.ports import ObjectStore, Repository
from korpus.composition import build_ingestion_service
from korpus.config import Settings, get_settings
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.ingestion_jobs import SqlIngestionJobQueue
from korpus.infrastructure.runtime import (
    create_object_store,
    create_quarantine_store,
    create_repository,
)
from korpus.security.auth import issue_token
from korpus.security.corpus_governance import CorpusGovernanceProfile
from korpus.security.reviewers import ReviewerRegistry
from korpus.security.scanning import ClamdInstreamScanner, DisabledMalwareScanner
from korpus.security.source_authenticity import SourceTrustProfile
from korpus.worker_lifecycle import install_stop_event


def _ingestion_service(
    settings: Settings,
    repository: Repository,
    object_store: ObjectStore,
    policy: PolicyEngine,
) -> IngestionService:
    scanner = (
        ClamdInstreamScanner(
            settings.clamd_host,
            settings.clamd_port,
            timeout_seconds=settings.malware_scan_timeout_seconds,
            max_bytes=settings.max_upload_bytes,
        )
        if settings.malware_scan_mode == "clamd"
        else DisabledMalwareScanner()
    )
    return build_ingestion_service(
        repository,
        object_store,
        policy,
        ExtractionSettings(
            ocr_enabled=settings.ocr_enabled,
            ocr_languages=settings.ocr_languages,
            max_pdf_pages=settings.max_pdf_pages,
            max_spans_per_document=settings.max_spans_per_document,
            max_chunk_chars=settings.max_chunk_chars,
            chunk_overlap_chars=settings.chunk_overlap_chars,
            ocr_total_timeout_seconds=settings.ocr_total_timeout_seconds,
            parser_sandbox_enabled=settings.parser_sandbox_enabled,
            parser_timeout_seconds=settings.parser_timeout_seconds,
            parser_memory_limit_mb=settings.parser_memory_limit_mb,
            parser_output_limit_bytes=settings.parser_output_limit_bytes,
        ),
        review_separation_required=settings.review_separation_required,
        malware_scanner=scanner,
        source_trust_profile=(
            SourceTrustProfile.load(
                settings.source_trust_profile_path, settings.source_trust_profile_sha256
            )
            if settings.source_trust_profile_path is not None
            else None
        ),
        require_source_signature=settings.require_source_signatures,
        reviewer_registry=(
            ReviewerRegistry.load(
                settings.reviewer_registry_path, settings.reviewer_registry_sha256
            )
            if settings.reviewer_registry_path is not None
            else None
        ),
        require_reviewer_credentials=(
            settings.environment in {"production", "controlled", "isolated"}
        ),
        corpus_governance=(
            CorpusGovernanceProfile.load(
                settings.corpus_governance_profile_path, settings.corpus_governance_profile_sha256
            )
            if settings.corpus_governance_profile_path is not None
            else None
        ),
        require_corpus_governance=settings.environment in {"production", "controlled", "isolated"},
    )


def _worker_id(explicit: str | None) -> str:
    return explicit or os.getenv("KORPUS_WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}"


def main() -> None:
    parser = argparse.ArgumentParser(prog="korpus")
    parser.add_argument(
        "command",
        choices=[
            "init-db",
            "verify-audit",
            "release-id",
            "issue-token",
            "reconcile-objects",
            "worker-once",
            "worker-loop",
        ],
    )
    # Стеля вже оголошена сервером (`jwt_max_lifetime_minutes`) і перевіряється в
    # `issue_token`; тут лише важіль. Без нього кожен токен жив рівно 60 хвилин, і
    # сесія агента вмирала посеред роботи — 401 посеред міркування читається як
    # «корпус мовчить», хоч це просто протермінований підпис.
    parser.add_argument(
        "--lifetime-minutes",
        type=int,
        default=60,
        help="Термін дії токена; стеля — jwt_max_lifetime_minutes сервера.",
    )
    parser.add_argument("--worker-id")
    parser.add_argument("--idle-seconds", type=float, default=1.0)
    args = parser.parse_args()
    settings = get_settings()
    policy = PolicyEngine()
    repository = create_repository(settings, policy)
    repository.initialize(create_schema=settings.schema_mode == "auto")
    object_store = create_object_store(settings)
    quarantine_store = create_quarantine_store(settings)
    try:
        if args.command == "init-db":
            print("database initialized")
            return
        if args.command == "verify-audit":
            print(repository.verify_audit().model_dump_json(indent=2))
            return
        if args.command == "reconcile-objects":
            expected = repository.object_inventory()
            actual_content = object_store.list_keys()
            actual_quarantine = quarantine_store.list_keys()
            report = {
                "content_missing": sorted(expected["content"] - actual_content),
                "content_orphaned": sorted(actual_content - expected["content"]),
                "quarantine_missing": sorted(expected["quarantine"] - actual_quarantine),
                "quarantine_orphaned": sorted(actual_quarantine - expected["quarantine"]),
            }
            import json

            print(json.dumps(report, indent=2))
            if report["content_missing"] or report["quarantine_missing"]:
                raise SystemExit(2)
            return
        if args.command in {"release-id", "issue-token"}:
            identity = Identity(
                subject=settings.dev_subject,
                roles=frozenset(
                    role.strip() for role in settings.dev_roles.split(",") if role.strip()
                ),
                clearance=AccessTier.parse(settings.dev_clearance),
                corpora=frozenset(
                    corpus.strip() for corpus in settings.dev_corpora.split(",") if corpus.strip()
                ),
                compartments=frozenset(
                    value.strip() for value in settings.dev_compartments.split(",") if value.strip()
                ),
            )
            if args.command == "release-id":
                print(
                    release_token(
                        repository, identity, identity.corpora, datetime.now(UTC).date()
                    ).release_id
                )
            else:
                print(issue_token(identity, settings, args.lifetime_minutes))
            return

        queue = SqlIngestionJobQueue(repository.engine)
        worker = IngestionWorker(
            queue,
            quarantine_store,
            _ingestion_service(settings, repository, object_store, policy),
            repository,
            worker_id=_worker_id(args.worker_id),
            lease_seconds=settings.ingestion_job_lease_seconds,
        )
        if args.command == "worker-once":
            result = worker.run_once()
            print(result.job.model_dump_json(indent=2) if result.job else "no queued job")
            return
        if args.idle_seconds <= 0 or args.idle_seconds > 60:
            raise SystemExit("--idle-seconds must be in (0, 60]")
        stop_event = install_stop_event()
        while not stop_event.is_set():
            try:
                result = worker.run_once()
            except Exception as exc:  # noqa: BLE001 — a worker must outlive one bad job
                # An unexpected error must not end the worker. If it did, one poison job
                # or one transport blip that escaped classification would stop every
                # ingestion until a human noticed the process was gone — a silent outage.
                # The job it was on stays leased and is reaped or re-claimed after expiry.
                print(
                    f"worker iteration failed, continuing: {type(exc).__name__}: {exc}",
                    flush=True,
                )
                stop_event.wait(args.idle_seconds)
                continue
            if not result.claimed:
                # Nothing to do this tick — a good moment to bury jobs a crashed worker
                # left RUNNING past their lease with no attempts remaining, writing the
                # audit event that worker never reached.
                for reaped in queue.reap_orphaned_leases():
                    repository.append_audit(
                        reaped.actor,
                        "ingestion.job_reaped",
                        "ingestion_job",
                        str(reaped.id),
                        {
                            "state": reaped.state.value,
                            "error_code": reaped.error_code,
                            "interpretation": (
                                "A worker died mid-job on its last attempt and left this "
                                "leased. It cannot be re-claimed, so it is moved to "
                                "dead_letter with a record, rather than sitting RUNNING "
                                "forever with no trace of why the document never appeared."
                            ),
                        },
                    )
                stop_event.wait(args.idle_seconds)
    finally:
        quarantine_store.close()
        object_store.close()
        repository.close()


if __name__ == "__main__":
    main()
