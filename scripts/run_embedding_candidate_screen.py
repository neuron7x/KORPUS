#!/usr/bin/env python3
"""Cheap dense-retrieval screen before any full-corpus embedding backfill."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]
from embedding_candidate_metrics import retrieval_metrics  # noqa: E402
from korpus.infrastructure.semantic import HttpEmbeddingProvider  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434/api/embed")
    parser.add_argument("--model", default="qwen3-embedding:0.6b")
    parser.add_argument("--dimensions", type=int, default=1024)
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals/datasets/reference.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "var/embedding-candidate-screen.json")
    args = parser.parse_args()

    raw = args.dataset.read_bytes()
    cases = [
        json.loads(line)
        for line in raw.decode("utf-8").splitlines()
        if line.strip() and json.loads(line)["kind"] == "retrieval"
    ]
    sentences = list(dict.fromkeys(str(case["evidence_sentence"]) for case in cases))
    sentence_index = {sentence: index for index, sentence in enumerate(sentences)}
    relevant = [{sentence_index[str(case["evidence_sentence"])]} for case in cases]
    provider = HttpEmbeddingProvider(
        args.endpoint, args.model, args.dimensions, timeout_seconds=30, max_attempts=2
    )
    started = time.perf_counter()
    inputs = sentences + [str(case["query"]) for case in cases]
    try:
        vectors = [
            vector
            for start in range(0, len(inputs), provider.max_batch_size)
            for vector in provider.embed_many(inputs[start : start + provider.max_batch_size])
        ]
    finally:
        provider.close()
    candidates = vectors[: len(sentences)]
    queries = vectors[len(sentences) :]
    duration = time.perf_counter() - started
    metrics = retrieval_metrics(queries, candidates, relevant)
    report = {
        "schema": "korpus.embedding-candidate-screen.v1",
        "status": "PASS",
        "measured_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "model": args.model,
        "dimensions": args.dimensions,
        "candidate_sentences": len(sentences),
        "metrics": metrics,
        "duration_seconds": duration,
        "embeddings_per_second": (len(sentences) + len(cases)) / duration,
        "promotion_authorized": False,
        "limitation": (
            "Candidate screen over frozen positive sentences, not the 118622-span corpus. "
            "It can reject a weak model but cannot authorize full-index activation."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
