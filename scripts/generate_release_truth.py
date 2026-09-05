#!/usr/bin/env python3
"""Generate current source-bound release truth views."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.provenance import DIGEST_SCOPE, compute_source_digest  # noqa: E402
from korpus.application.release_truth import (  # noqa: E402
    blocker_registry,
    claim_ledger,
    inventory,
    status_ontology,
)
from release_identity import release_tag  # noqa: E402


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _blockers(source_digest: str, release: str) -> dict[str, Any]:
    return blocker_registry(ROOT, source_digest, release)


def main() -> int:
    source_digest, release = compute_source_digest(ROOT), release_tag()
    counts = inventory(ROOT)
    _write(
        ROOT / "reports/EXECUTABLE_EVIDENCE_INDEX_CURRENT.json",
        {
            "schema": "korpus.executable-evidence-index.v2",
            **counts,
            "source_tree_sha256": source_digest,
            "digest_scope": DIGEST_SCOPE,
            "release": release,
            "method": "AST enumeration over current source/test tree",
        },
    )
    final = ROOT / f"reports/release/{release}/final"
    _write(final / "BLOCKER_REGISTRY.json", blocker_registry(ROOT, source_digest, release))
    _write(final / "CLAIM_LEDGER.json", claim_ledger(ROOT, source_digest, release))
    _write(final / "STATUS_ONTOLOGY.json", status_ontology())
    print(json.dumps({"release": release, "source_tree_sha256": source_digest, **counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
