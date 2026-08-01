from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.policy import AuthorizationError, PolicyEngine
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    DocumentCreate,
    Identity,
    QueryRequest,
    ReviewState,
    ReviewTransition,
    VersionCreate,
)
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.repository import SqlRepository

DATASET = Path("evals/datasets/assurance.jsonl")
PROTOCOL = Path("evals/EVALUATION_PROTOCOL.md")


def _approve(ingestion: IngestionService, actor: Identity, version_id: Any) -> None:
    for state in (ReviewState.METADATA_REVIEWED, ReviewState.CONTENT_REVIEWED, ReviewState.APPROVED):
        ingestion.transition(
            actor,
            version_id,
            ReviewTransition(target=state, note="frozen assurance evaluation independent review"),
        )


def _ingest(
    ingestion: IngestionService,
    admin: Identity,
    *,
    title: str,
    text: bytes,
    corpus: str = "public",
    tier: AccessTier = AccessTier.PUBLIC,
    classification: str = "public",
    revision: str = "1",
    effective_from: date | None = None,
    supersedes: Any = None,
    document_id: Any = None,
):
    version = VersionCreate(
        revision=revision,
        authority=AuthorityClass.OFFICIAL_UA,
        effective_from=effective_from,
        supersedes_version_id=supersedes,
    )
    if document_id is None:
        result = ingestion.ingest(
            admin,
            DocumentCreate(
                canonical_title=title,
                corpus_id=corpus,
                issuer="Evaluation Authority",
                document_type="order",
                access_tier=tier,
                classification=classification,
            ),
            version,
            f"{title}.txt",
            "text/plain",
            text,
        )
    else:
        result = ingestion.ingest_version(
            admin,
            document_id,
            version,
            f"{title}.txt",
            "text/plain",
            text,
        )
    _approve(ingestion, admin, result.version.id)
    return result


def _projection(answer: Any) -> dict[str, Any]:
    value = answer.model_dump(mode="json")
    value.pop("id", None)
    value.pop("created_at", None)
    return value


def main() -> None:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    dataset_hash = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    protocol_hash = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    from build_system_manifest import build as build_system_manifest
    system_manifest = build_system_manifest()
    system_manifest_bytes = (json.dumps(system_manifest, indent=2, sort_keys=True) + "\n").encode()
    system_manifest_hash = hashlib.sha256(system_manifest_bytes).hexdigest()
    with tempfile.TemporaryDirectory(prefix="korpus-eval-") as directory:
        root = Path(directory)
        policy = PolicyEngine()
        repository = SqlRepository(
            f"sqlite:///{root / 'eval.db'}",
            "eval-audit-key",
            policy,
            root / "audit-anchor.json",
        )
        repository.initialize()
        store = LocalObjectStore(root / "objects")
        admin = Identity(
            subject="eval-admin",
            roles=frozenset({"admin", "curator", "reviewer", "user", "auditor"}),
            clearance=AccessTier.RESTRICTED,
            corpora=frozenset({"public", "training", "restricted-demo"}),
        )
        public = Identity(
            subject="eval-public",
            roles=frozenset({"user"}),
            clearance=AccessTier.PUBLIC,
            corpora=frozenset({"public"}),
        )
        authenticated = Identity(
            subject="eval-authenticated",
            roles=frozenset({"user"}),
            clearance=AccessTier.AUTHENTICATED,
            corpora=frozenset({"public", "training"}),
        )
        identities = {"public": public, "authenticated": authenticated, "admin": admin}
        ingestion = IngestionService(repository, store, policy, ExtractionSettings(False, "ukr+eng"))
        _ingest(
            ingestion,
            admin,
            title="public-order",
            text=Path("evals/fixtures/public_order.txt").read_bytes(),
        )
        _ingest(
            ingestion,
            admin,
            title="operations",
            text=Path("evals/fixtures/operations.txt").read_bytes(),
        )
        _ingest(
            ingestion,
            admin,
            title="source-injection",
            text=Path("evals/fixtures/source_injection.txt").read_bytes(),
        )
        _ingest(
            ingestion,
            admin,
            title="restricted",
            text=b"RESTRICTED-EVAL-MARKER is visible only inside the restricted corpus.",
            corpus="restricted-demo",
            tier=AccessTier.RESTRICTED,
            classification="restricted",
        )
        _ingest(
            ingestion,
            admin,
            title="training",
            text=b"TRAINING-INTERNAL-MARKER identifies the authenticated training procedure.",
            corpus="training",
            tier=AccessTier.AUTHENTICATED,
            classification="internal",
        )
        old = _ingest(
            ingestion,
            admin,
            title="versioned-procedure",
            text=b"OLD-PROCEDURE-MARKER identifies the historical procedure.",
            effective_from=date(2025, 1, 1),
        )
        _ingest(
            ingestion,
            admin,
            title="versioned-procedure-v2",
            text=b"NEW-PROCEDURE-MARKER identifies the current procedure.",
            revision="2",
            effective_from=date(2026, 1, 1),
            supersedes=old.version.id,
            document_id=old.document.id,
        )
        service = ExtractiveAnswerService(
            repository,
            HybridLexicalRetriever(repository),
            policy,
            AnswerPolicy(
                minimum_score=0.08,
                minimum_query_coverage=0.50,
                minimum_support_score=0.08,
                calibration_id=f"frozen-assurance:{dataset_hash[:12]}",
            ),
        )

        details: list[dict[str, Any]] = []
        status_correct = 0
        citation_checks = 0
        citation_failures = 0
        leakage_failures = 0
        determinism_failures = 0
        answered_expected = answered_actual = 0
        abstain_expected = abstain_actual = 0

        for row in rows:
            identity = identities[row["identity"]]
            query = QueryRequest(
                text=row["query"],
                corpus_ids=row.get("corpus_ids", []),
                as_of=date.fromisoformat(row.get("as_of", "2026-07-31")),
            )
            try:
                first = service.execute(identity, query)
                second = service.execute(identity, query)
                actual = first.status.value
                deterministic = _projection(first) == _projection(second)
                if not deterministic:
                    determinism_failures += 1
                serialized = first.model_dump_json()
                forbidden = row.get("forbidden", [])
                leaked = any(marker in serialized for marker in forbidden)
                leakage_failures += int(leaked)
                expected_quote = row.get("expected_quote")
                quote_ok = expected_quote is None or any(
                    expected_quote in citation.quote for citation in first.citations
                )
                reason_ok = row.get("expected_reason") in {None, first.decision_reason}
                for citation in first.citations:
                    citation_checks += 1
                    accessible = repository.list_retrievable_spans(identity, identity.corpora, query.as_of)
                    match = next((span for span, _, _ in accessible if span.id == citation.span_id), None)
                    valid = (
                        match is not None
                        and match.text[citation.quote_start : citation.quote_end] == citation.quote
                        and hashlib.sha256(citation.quote.encode()).hexdigest() == citation.quote_hash
                    )
                    citation_failures += int(not valid)
                ok = actual == row["expected_status"] and quote_ok and reason_ok and not leaked and deterministic
            except AuthorizationError:
                actual = "access_denied"
                ok = actual == row["expected_status"]
                quote_ok = True
                reason_ok = True
                leaked = False
                deterministic = True
            status_correct += int(actual == row["expected_status"])
            answered_expected += int(row["expected_status"] == "answered")
            answered_actual += int(actual == "answered")
            abstain_expected += int(row["expected_status"] == "insufficient_evidence")
            abstain_actual += int(actual == "insufficient_evidence")
            details.append(
                {
                    "id": row["id"],
                    "ok": ok,
                    "expected": row["expected_status"],
                    "actual": actual,
                    "quote_ok": quote_ok,
                    "reason_ok": reason_ok,
                    "leaked": leaked,
                    "deterministic": deterministic,
                    "retrieval_score": first.retrieval_score if "first" in locals() else 0.0,
                    "query_coverage": first.query_coverage if "first" in locals() else 0.0,
                    "decision_reason": first.decision_reason if "first" in locals() else "access_denied",
                    "claims": [claim.text for claim in first.claims] if "first" in locals() else [],
                }
            )

        passed = sum(int(item["ok"]) for item in details)
        report = {
            "schema": 2,
            "dataset": str(DATASET),
            "dataset_sha256": dataset_hash,
            "evaluation_protocol": str(PROTOCOL),
            "evaluation_protocol_sha256": protocol_hash,
            "system_manifest_sha256": system_manifest_hash,
            "system_manifest_root_sha256": system_manifest["manifest_root_sha256"],
            "source_commit": system_manifest["commit"],
            "calibration_status": "UNVALIDATED_TEST_FIXTURE",
            "passed": passed,
            "total": len(rows),
            "pass_rate": passed / max(len(rows), 1),
            "status_accuracy": status_correct / max(len(rows), 1),
            "citation_checks": citation_checks,
            "citation_failures": citation_failures,
            "leakage_failures": leakage_failures,
            "determinism_failures": determinism_failures,
            "answered_expected": answered_expected,
            "answered_actual": answered_actual,
            "abstain_expected": abstain_expected,
            "abstain_actual": abstain_actual,
            "audit_valid": repository.verify_audit().valid,
            "details": details,
        }
        Path("var").mkdir(exist_ok=True)
        Path("var/system-manifest.json").write_bytes(system_manifest_bytes)
        Path("var/eval-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if (
            passed != len(rows)
            or citation_failures
            or leakage_failures
            or determinism_failures
            or not report["audit_valid"]
        ):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
