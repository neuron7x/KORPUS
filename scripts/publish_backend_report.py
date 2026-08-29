#!/usr/bin/env python3
"""Turn a sharded regression merge into the backend report the preflight reads.

`run_local_production_preflight.py` requires `reports/release/<tag>/FULL_BACKEND_REPORT.json`
and refuses it unless it is bound to the current source tree. Nothing produced that file.
It was written by hand — the copy in the tree cites `var/regression-v097-current2/merge.json`,
a path from an ad-hoc run — and the preflight has read a stale artefact ever since, which
is why its eleven local checks were all failing on binding rather than on substance.

The merge already carries every number the report states: the release, the source digest,
the collection digest, the shard count and the JUnit totals. This is the projection, and
having it means the shape can no longer drift from the run that produced it.

The source digest is not copied blindly. A merge from another tree is refused here rather
than published and refused four stages later by the gate that reads it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--merge", type=Path, default=ROOT / "reports/regression/FULL_REGRESSION_CURRENT.json"
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if not args.merge.is_file():
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason": f"no regression merge at {args.merge.relative_to(ROOT)};"
                    " run `make backend-report` or the shards it drives",
                },
                ensure_ascii=False,
            )
        )
        return 1

    merge = json.loads(args.merge.read_text(encoding="utf-8"))
    release = release_tag(ROOT)
    digest = compute_source_digest(ROOT)

    failures: list[str] = []
    if merge.get("source_digest") != digest:
        failures.append(
            f"merge was produced from another tree: {str(merge.get('source_digest'))[:12]}"
            f" != {digest[:12]}"
        )
    if merge.get("release_tag") != release:
        failures.append(f"merge names release {merge.get('release_tag')}, not {release}")
    if failures:
        print(json.dumps({"status": "FAIL", "failures": failures}, ensure_ascii=False, indent=2))
        return 1

    junit = merge.get("junit", {})
    report = {
        "schema": "korpus.full-backend-report.v2",
        "status": merge.get("status", "FAIL"),
        "release": release,
        "source_tree_sha256": digest,
        "collection_digest": merge.get("collection_digest"),
        "collected": merge.get("collection_count"),
        "passed": int(junit.get("tests", 0))
        - int(junit.get("failures", 0))
        - int(junit.get("errors", 0))
        - int(junit.get("skipped", 0)),
        "failed": int(junit.get("failures", 0)),
        "errors": int(junit.get("errors", 0)),
        "skipped": int(junit.get("skipped", 0)),
        "shards": merge.get("shards"),
        "evidence_source": str(args.merge.relative_to(ROOT)),
    }
    out = args.out or ROOT / f"reports/release/{release}/FULL_BACKEND_REPORT.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
