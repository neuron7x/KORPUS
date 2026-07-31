from __future__ import annotations

import json
import tempfile
from pathlib import Path

from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.policy import AuthorizationError, PolicyEngine
from korpus.application.retrieval import LexicalRetriever
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


def main() -> None:
    rows = [json.loads(line) for line in Path("evals/datasets/frozen.jsonl").read_text().splitlines() if line.strip()]
    with tempfile.TemporaryDirectory(prefix="korpus-eval-") as directory:
        root = Path(directory)
        policy = PolicyEngine()
        repository = SqlRepository(f"sqlite:///{root / 'eval.db'}", "eval-key", policy)
        repository.initialize()
        store = LocalObjectStore(root / "objects")
        admin = Identity(subject="eval-admin", roles=frozenset({"admin", "curator", "reviewer", "user"}),
                         clearance=AccessTier.RESTRICTED, corpora=frozenset({"public", "restricted-demo"}))
        public = Identity(subject="eval-public", roles=frozenset({"user"}), clearance=AccessTier.PUBLIC,
                          corpora=frozenset({"public"}))
        ingestion = IngestionService(repository, store, policy, ExtractionSettings(False, "ukr+eng"))
        fixture = Path("evals/fixtures/public_order.txt").read_bytes()
        result = ingestion.ingest(admin, DocumentCreate(canonical_title="Frozen public order", corpus_id="public",
            issuer="Evaluation Authority", document_type="order"),
            VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA), "public.txt", "text/plain", fixture)
        for state in (ReviewState.METADATA_REVIEWED, ReviewState.CONTENT_REVIEWED, ReviewState.APPROVED):
            ingestion.transition(admin, result.version.id, ReviewTransition(target=state, note="frozen evaluation review"))
        restricted = ingestion.ingest(admin, DocumentCreate(canonical_title="Restricted marker", corpus_id="restricted-demo",
            issuer="Evaluation Authority", document_type="restricted", access_tier=AccessTier.RESTRICTED,
            classification="restricted"), VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
            "restricted.txt", "text/plain", b"RESTRICTED-EVAL-MARKER must never cross the public boundary.")
        for state in (ReviewState.METADATA_REVIEWED, ReviewState.CONTENT_REVIEWED, ReviewState.APPROVED):
            ingestion.transition(admin, restricted.version.id, ReviewTransition(target=state, note="restricted evaluation review"))
        service = ExtractiveAnswerService(repository, LexicalRetriever(repository), policy,
            AnswerPolicy(minimum_score=0.10, minimum_query_coverage=0.20))
        passed = 0
        details = []
        for row in rows:
            identity = public if row["identity"] == "public" else admin
            try:
                answer = service.execute(identity, QueryRequest(text=row["query"], corpus_ids=row.get("corpus_ids", [])))
                actual = answer.status.value
                leak = "RESTRICTED-EVAL-MARKER" in answer.model_dump_json()
                ok = actual == row["expected_status"] and not leak
            except AuthorizationError:
                actual = "access_denied"
                ok = actual == row["expected_status"]
            passed += int(ok)
            details.append({"id": row["id"], "ok": ok, "expected": row["expected_status"], "actual": actual})
        report = {"passed": passed, "total": len(rows), "pass_rate": passed / max(len(rows), 1), "details": details}
        Path("var").mkdir(exist_ok=True)
        Path("var/eval-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if passed != len(rows):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
