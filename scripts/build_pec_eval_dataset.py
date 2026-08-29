#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pec_common import read_jsonl, receipt, sha256_file, write_json, write_jsonl

ROOT = Path(__file__).resolve().parents[1]


def _sequence(row: dict[str, object], key: str) -> list[object]:
    """A dataset field is `object`; iterating one without checking is a runtime surprise."""
    value = row.get(key, [])
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ValueError(f"dataset field {key!r} must be a list")
    return list(value)


def normalize(row: dict[str, object]) -> dict[str, object]:
    query = str(row.get("query", "")).strip()
    if not query:
        raise ValueError("evaluation row has empty query")
    group = str(
        row.get("sampled_from_version")
        or row.get("source_title")
        or row.get("stratum")
        or row.get("id")
    )
    bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 10
    partition = "train" if bucket < 6 else ("calibration" if bucket < 8 else "locked_eval")
    return {
        "id": str(row.get("id")),
        "query": query,
        "group_id": group,
        "partition": partition,
        "expected_status": row.get("expected_status") or row.get("expect") or "review",
        "gold_version_ids": sorted(str(x) for x in _sequence(row, "must_cite_one_of_if_answered")),
        "stratum": str(row.get("stratum", "unspecified")),
        "kind": str(row.get("kind", "answer")),
        "source_record_sha256": hashlib.sha256(
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=ROOT / "evals/datasets/reference.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "evals/datasets/pec/pec_eval.jsonl")
    ap.add_argument("--receipt", type=Path, default=ROOT / "reports/PEC_DATASET_BUILD_CURRENT.json")
    a = ap.parse_args()
    rows = [normalize(row) for row in read_jsonl(a.source)]
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate evaluation ids")
    write_jsonl(a.out, rows)
    report = receipt(
        "pec_dataset_build",
        {
            "status": "PASS",
            "source": str(a.source.resolve().relative_to(ROOT)),
            "source_sha256": sha256_file(a.source),
            "dataset": str(a.out.resolve().relative_to(ROOT)),
            "dataset_sha256": sha256_file(a.out),
            "rows": len(rows),
            "groups": len({r["group_id"] for r in rows}),
            "partitions": {
                name: sum(r["partition"] == name for r in rows)
                for name in ("train", "calibration", "locked_eval")
            },
        },
    )
    write_json(a.receipt, report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
