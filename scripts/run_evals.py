#!/usr/bin/env python3
"""Execute the eval fixtures against the real answer pipeline.

A fixture nobody runs is a wish. This runner is deliberately blunt: it builds the
service from the same code the API uses, replays each case, and exits non-zero on
the first disagreement — including the case where the dataset itself is empty,
because an empty run that prints "0 failures" is the most expensive kind of green.

Usage: python3 scripts/run_evals.py [--dataset evals/datasets/seed.jsonl] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.answer_query import AnswerPolicy, AnswerQuery  # noqa: E402
from korpus.application.ports import Generator  # noqa: E402
from korpus.domain.access import Principal  # noqa: E402
from korpus.domain.models import (  # noqa: E402
    AccessTier,
    AnswerStatus,
    AuthorityClass,
    Citation,
    Claim,
    EvidenceSpan,
    Query,
    ReviewState,
)
from korpus.infrastructure.in_memory import (  # noqa: E402
    EvidenceBoundStubGenerator,
    FixedClock,
    InMemoryAuditSink,
)
from korpus.infrastructure.lexical import LexicalRetriever  # noqa: E402

# Fixtures are validated against this whitelist before anything runs. A misspelled
# expectation used to be silently optional: `expected_min_citaions` disabled the
# assertion and the case still passed.
ALLOWED_KEYS = {
    "id", "query", "principal", "corpus", "request_unheld_corpus", "generator",
    "expected_status", "expected_min_citations", "expected_min_coverage",
    "expected_first_chunk", "forbidden_text", "rationale",
}
REQUIRED_KEYS = {"id", "query", "expected_status", "rationale"}
ALLOWED_CORPUS_KEYS = {
    "chunk", "document", "version", "corpus", "granted", "text", "quote", "title",
    "page", "score", "access_tier", "review_state", "authority", "valid_until",
    "superseded_by",
}


class UncitedGenerator:
    """Declared by a fixture that needs the human-review path, not a hidden default."""

    async def compose(self, query: Query, evidence: list[EvidenceSpan]) -> list[Claim]:
        del query, evidence
        return [Claim(text="Твердження без джерела.", citation_indexes=())]


GENERATORS: dict[str, Callable[[], Generator]] = {
    "stub": EvidenceBoundStubGenerator,
    "uncited": UncitedGenerator,
}

NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
CLOCK = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    expected: str
    actual: str
    detail: str = ""


def stable_uuid(name: str) -> UUID:
    """Deterministic ids so a failing case is reproducible from its fixture alone."""
    return uuid5(NAMESPACE, name)


def build_span(case_id: str, entry: dict[str, Any]) -> EvidenceSpan:
    chunk = stable_uuid(f"{case_id}:{entry['chunk']}")
    document = stable_uuid(f"{case_id}:{entry.get('document', entry['chunk'])}")
    version = stable_uuid(f"{case_id}:{entry.get('version', entry['chunk'])}")
    valid_until = entry.get("valid_until")
    corpus = stable_uuid(f"{case_id}:{entry.get('corpus', 'default')}")
    return EvidenceSpan(
        citation=Citation(
            document_id=document,
            chunk_id=chunk,
            title=entry.get("title", "Джерело"),
            page=entry.get("page", 1),
            quote=entry.get("quote", entry["text"]),
        ),
        chunk_id=chunk,
        document_id=document,
        document_version_id=version,
        corpus_id=corpus,
        text=entry["text"],
        retrieval_score=float(entry.get("score", 1.0)),
        access_tier=AccessTier(entry.get("access_tier", "public")),
        review_state=ReviewState(entry.get("review_state", "approved")),
        authority=AuthorityClass(entry.get("authority", "official_ua")),
        valid_until=datetime.fromisoformat(valid_until) if valid_until else None,
        superseded_by=UUID(entry["superseded_by"]) if entry.get("superseded_by") else None,
    )


async def run_case(case: dict[str, Any]) -> CaseResult:
    case_id = str(case["id"])
    spans = [build_span(case_id, entry) for entry in case.get("corpus", [])]
    retriever = LexicalRetriever(spans)
    service = AnswerQuery(
        retriever=retriever,
        generator=GENERATORS[case.get("generator", "stub")](),
        audit=InMemoryAuditSink(),
        policy=AnswerPolicy(),
        clock=FixedClock(CLOCK),
    )
    # The reader is granted exactly the corpora this case's own fixtures declare, so a
    # scope defect shows up as a failing case rather than as a wider search.
    granted = frozenset(
        stable_uuid(f"{case_id}:{entry.get('corpus', 'default')}")
        for entry in case.get("corpus", [])
        if entry.get("granted", True)
    )
    principal = Principal(
        subject_id=case.get("principal", {}).get("subject_id", "eval"),
        tier=AccessTier(case.get("principal", {}).get("tier", "public")),
        authorized_corpora=granted,
    )
    corpus_ids = [uuid4()] if case.get("request_unheld_corpus") else []
    answer = await service.execute(Query(text=case["query"], corpus_ids=corpus_ids), principal)

    expected = AnswerStatus(case["expected_status"])
    problems: list[str] = []
    if answer.status is not expected:
        problems.append(f"status {answer.status.value} != {expected.value}")

    minimum = int(case.get("expected_min_citations", 0))
    if len(answer.citations) < minimum:
        problems.append(f"citations {len(answer.citations)} < {minimum}")
    if minimum == 0 and answer.citations:
        problems.append("refusal carried citations")

    coverage_floor = case.get("expected_min_coverage")
    if coverage_floor is not None and answer.citation_coverage < float(coverage_floor):
        problems.append(f"coverage {answer.citation_coverage:.2f} < {coverage_floor}")

    forbidden = case.get("forbidden_text")
    if forbidden and forbidden in answer.model_dump_json():
        problems.append("response disclosed material it should not name")

    first = case.get("expected_first_chunk")
    if first:
        wanted = stable_uuid(f"{case_id}:{first}")
        if not answer.citations or answer.citations[0].chunk_id != wanted:
            problems.append(f"first citation is not {first}")

    return CaseResult(
        case_id=case_id,
        passed=not problems,
        expected=expected.value,
        actual=answer.status.value,
        detail="; ".join(problems),
    )


def validate_case(case: dict[str, Any], where: str) -> None:
    """Reject a fixture the runner would otherwise half-execute."""
    unknown = set(case) - ALLOWED_KEYS
    if unknown:
        raise SystemExit(f"{where}: unknown fixture keys {sorted(unknown)}")
    missing = REQUIRED_KEYS - set(case)
    if missing:
        raise SystemExit(f"{where}: missing required keys {sorted(missing)}")
    try:
        AnswerStatus(case["expected_status"])
    except ValueError as error:
        raise SystemExit(f"{where}: {error}") from error
    if case.get("generator", "stub") not in GENERATORS:
        raise SystemExit(f"{where}: unknown generator {case['generator']!r}")
    for entry in case.get("corpus", []):
        unknown_entry = set(entry) - ALLOWED_CORPUS_KEYS
        if unknown_entry:
            raise SystemExit(f"{where}: unknown corpus keys {sorted(unknown_entry)}")
        if "chunk" not in entry or "text" not in entry:
            raise SystemExit(f"{where}: a corpus entry needs 'chunk' and 'text'")


def load(dataset: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for number, line in enumerate(dataset.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            case = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise SystemExit(f"{dataset}:{number}: malformed JSON — {error}") from error
        validate_case(case, f"{dataset.name}:{number}")
        cases.append(case)
    identifiers = [case["id"] for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise SystemExit(f"{dataset}: duplicate case ids")
    return cases


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evals/datasets/seed.jsonl")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--min-cases", type=int, default=1)
    args = parser.parse_args()

    dataset = (ROOT / args.dataset).resolve()
    if not dataset.exists():
        print(f"FAIL: dataset not found: {dataset}")
        return 2

    cases = load(dataset)
    manifest_path = dataset.parent / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_cases = int(manifest.get(dataset.name, {}).get("cases", args.min_cases))
    if len(cases) < expected_cases:
        print(f"FAIL: {len(cases)} cases loaded, {expected_cases} recorded in manifest.json")
        return 2
    required_statuses = set(manifest.get(dataset.name, {}).get("statuses", []))
    covered = {case["expected_status"] for case in cases}
    if not required_statuses <= covered:
        print(f"FAIL: dataset no longer covers {sorted(required_statuses - covered)}")
        return 2

    results = [await run_case(case) for case in cases]
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    if args.json:
        print(
            json.dumps(
                {
                    "dataset": str(dataset.relative_to(ROOT)),
                    "cases": len(results),
                    "passed": len(passed),
                    "failed": len(failed),
                    "pass_rate": len(passed) / len(results),
                    "failures": [
                        {"id": r.case_id, "expected": r.expected, "actual": r.actual,
                         "detail": r.detail}
                        for r in failed
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for result in results:
            mark = "PASS" if result.passed else "FAIL"
            suffix = f" — {result.detail}" if result.detail else ""
            print(f"[{mark}] {result.case_id}: {result.actual}{suffix}")
        print(f"\n{len(passed)}/{len(results)} cases passed")

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
