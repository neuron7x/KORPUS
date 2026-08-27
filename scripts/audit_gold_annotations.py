#!/usr/bin/env python3
"""Evaluate a human annotation ledger without manufacturing human evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.gold_annotation import (  # noqa: E402
    Adjudication,
    Annotation,
    GoldAdmissionPolicy,
    GoldBindings,
    evaluate_gold_annotations,
)


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as out:
        temporary = Path(out.name)
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "reports/GOLD_ANNOTATION_CURRENT.json")
    args = parser.parse_args()
    payload = json.loads(args.ledger.read_text(encoding="utf-8"))
    if payload.get("schema") != "korpus.gold-annotation-ledger.v1":
        raise SystemExit("gold annotation ledger schema is invalid")
    report = evaluate_gold_annotations(
        [Annotation.model_validate(row) for row in payload.get("annotations", [])],
        [Adjudication.model_validate(row) for row in payload.get("adjudications", [])],
        tuning_query_ids=frozenset(map(str, payload.get("tuning_query_ids", []))),
        policy=GoldAdmissionPolicy.model_validate(payload.get("policy", {})),
    )
    report["bindings"] = GoldBindings.model_validate(payload.get("bindings", {})).model_dump(
        mode="json"
    )
    _write(args.out, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
