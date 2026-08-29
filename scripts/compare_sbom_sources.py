#!/usr/bin/env python3
"""Two SBOMs of one tree, and what their disagreement means.

`source-sbom.cdx.json` is generated from the dependency locks: deterministic, in git,
hashed by the source manifest. `syft dir:.` scans the working tree instead and finds
whatever is actually on disk. They were writing to the same path, so the CI job silently
replaced the committed file with a scan of a different shape, and `source:package` then
refused the tree it had just built with `source digest mismatch: source-sbom.cdx.json`.

Overwriting one with the other loses the only thing the pair is good for. The locks say
what the build is *entitled* to resolve; the scan says what is *present*. A component in
the scan and not in the locks is a dependency nothing pinned — the supply-chain question
worth asking, and the one a single SBOM cannot answer.

The comparison is asymmetric on purpose. Extra components in the scan are reported and,
by default, fail: they are unpinned material in the tree. Components in the locks that
the scanner did not see are recorded but do not fail, because a scanner missing a wheel
it cannot classify is a limitation of the scanner, not a fault in the tree.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def components(path: Path) -> dict[str, str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for item in document.get("components", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().lower()
        if name:
            found[name] = str(item.get("version", ""))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locks", type=Path, default=ROOT / "source-sbom.cdx.json")
    parser.add_argument("--scan", type=Path, default=ROOT / "var/tree-sbom.cdx.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/sbom-comparison.json")
    parser.add_argument(
        "--allow-unpinned",
        action="store_true",
        help="report unpinned components without failing; for a first run on a new scanner",
    )
    args = parser.parse_args()

    if not args.scan.is_file():
        print(
            json.dumps(
                {
                    "schema": "korpus.sbom-comparison.v1",
                    "status": "SKIPPED",
                    "reason": f"no tree scan at {args.scan.relative_to(ROOT)}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    locked = components(args.locks)
    scanned = components(args.scan)
    unpinned = sorted(set(scanned) - set(locked))
    unseen = sorted(set(locked) - set(scanned))
    drifted = sorted(
        name
        for name in set(locked) & set(scanned)
        if scanned[name] and locked[name] and scanned[name] != locked[name]
    )

    failures: list[str] = []
    if unpinned and not args.allow_unpinned:
        failures.append(f"components present in the tree but pinned by no lock: {unpinned}")
    if drifted:
        failures.append(f"version disagreement between lock and tree: {drifted}")

    report: dict[str, Any] = {
        "schema": "korpus.sbom-comparison.v1",
        "status": "FAIL" if failures else "PASS",
        "locked_components": len(locked),
        "scanned_components": len(scanned),
        "unpinned_in_tree": unpinned,
        "in_locks_but_not_scanned": unseen,
        "version_disagreement": drifted,
        "failures": failures,
        "interpretation": (
            "The locks state what the build may resolve; the scan states what is on disk. "
            "Extra components in the scan are unpinned material and fail. Components the "
            "scanner did not classify are recorded and do not fail — that is a limit of "
            "the scanner, not a fault in the tree."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
