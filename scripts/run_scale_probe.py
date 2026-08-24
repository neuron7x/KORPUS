#!/usr/bin/env python3
"""Local reproducible scale probe for candidate retrieval.

The result is an environment-specific measurement, not a universal benchmark.
It verifies bounded candidate generation and records latency procedure/provenance.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import tempfile
import time
from datetime import date
from pathlib import Path

from korpus.application.provenance import PROVENANCE_KEY, stamp
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    ReviewState,
)
from korpus.infrastructure.repository import SqlRepository

ROOT = Path(__file__).resolve().parents[1]
SPAN_COUNT = int(os.getenv("KORPUS_SCALE_SPANS", "5000"))
ITERATIONS = int(os.getenv("KORPUS_SCALE_ITERATIONS", "80"))
CANDIDATE_BUDGET = int(os.getenv("KORPUS_SCALE_CANDIDATES", "256"))


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))
    return ordered[index]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="korpus-scale-") as temporary:
        root = Path(temporary)
        repository = SqlRepository(
            f"sqlite:///{root / 'scale.db'}",
            "scale-probe-audit-key",
            audit_anchor_path=root / "anchor.json",
        )
        repository.initialize()
        actor = Identity(
            subject="scale-probe",
            roles=frozenset({"admin", "user"}),
            clearance=AccessTier.RESTRICTED,
            corpora=frozenset({"public"}),
        )
        document = DocumentRecord(
            canonical_title="Synthetic scale corpus",
            corpus_id="public",
            issuer="Scale Probe",
            jurisdiction="UA",
            document_type="synthetic",
            access_tier=AccessTier.PUBLIC,
            classification=Classification.PUBLIC,
        )
        version = DocumentVersionRecord(
            document_id=document.id,
            revision="scale-1",
            source_hash="a" * 64,
            object_key="synthetic/scale",
            mime_type="text/plain",
            authority=AuthorityClass.OFFICIAL_UA,
            review_state=ReviewState.APPROVED,
            # An approved version governs from a stated date; without one the candidate
            # query excludes it and the probe measures an empty corpus at full speed.
            publication_date=date(2020, 1, 1),
            is_current=True,
        )
        records = [
            EvidenceSpanRecord(
                version_id=version.id,
                ordinal=index,
                text=(
                    "ALPHA-OMEGA deterministic target evidence for bounded candidate retrieval."
                    if index == SPAN_COUNT // 2
                    else (
                        f"Routine synthetic evidence fragment number {index} "
                        "with common corpus language."
                    )
                ),
            )
            for index in range(SPAN_COUNT)
        ]
        started = time.perf_counter()
        repository.create_document_bundle(
            actor,
            document,
            version,
            records,
            {"probe": "scale", "spans": SPAN_COUNT},
        )
        ingest_seconds = time.perf_counter() - started
        retriever = HybridLexicalRetriever(repository, candidate_budget=CANDIDATE_BUDGET)
        query = "ALPHA-OMEGA deterministic target"
        retriever.search(actor, query, actor.corpora, date.today())
        durations: list[float] = []
        top_hits = 0
        for _ in range(ITERATIONS):
            started = time.perf_counter_ns()
            result = retriever.search(actor, query, actor.corpora, date.today())
            durations.append((time.perf_counter_ns() - started) / 1_000_000)
            top_hits += int(bool(result) and "ALPHA-OMEGA" in result[0].span.text)
        candidate_count = len(
            repository.search_retrievable_spans(
                actor, actor.corpora, date.today(), query, CANDIDATE_BUDGET
            )
        )
        report = {
            "schema_version": 1,
            "status": (
                "PASS" if top_hits == ITERATIONS and candidate_count <= CANDIDATE_BUDGET else "FAIL"
            ),
            "metric_status": "ANCHORED_LOCAL_MEASUREMENT",
            "procedure": {
                "database": "SQLite FTS5",
                "spans": SPAN_COUNT,
                "iterations": ITERATIONS,
                "warmup_queries": 1,
                "candidate_budget": CANDIDATE_BUDGET,
                "query": query,
            },
            "results": {
                "ingest_seconds": ingest_seconds,
                "query_latency_ms_p50": statistics.median(durations),
                "query_latency_ms_p95": percentile(durations, 0.95),
                "query_latency_ms_max": max(durations),
                "candidate_count": candidate_count,
                "top1_recall": top_hits / ITERATIONS,
            },
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "processor": platform.processor() or "UNKNOWN",
            },
            "limitations": [
                "Synthetic local probe; not a production SLA.",
                "PostgreSQL network, concurrency and disk behavior are not represented.",
            ],
            PROVENANCE_KEY: stamp(ROOT, "scripts/run_scale_probe.py"),
        }
        output = ROOT / "var/scale-report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
