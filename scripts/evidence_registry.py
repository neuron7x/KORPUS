#!/usr/bin/env python3
"""Keep the gate reports for the system's life, not the pipeline's, and seal them.

OPS-003. Every gate in this tree leaves a report — mutation, coverage, the load probe, the
chaos matrix, the reference evaluation, the scanners — and every one of them lives in
`var/`, which is cleaned, or in a CI artefact, which expires in weeks. The question they
answer is asked years later: what did this system say in August, and what showed it was
sound at the time.

So the reports are copied into a registry under their digest, and the registry carries a
digest over its own contents. Copied rather than referenced: a registry of paths is a
registry of things that have since changed.

Sealed rather than signed. A digest catches a careless edit and does not stop a deliberate
one — anyone who can rewrite an entry can recompute the digest. What stops that is a
signature with a key the editor does not hold, and that is `corpus_release.py`'s job for
the corpus and a KMS's job for everything else. The distinction is written into the report
rather than left for a reader to assume.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: What is worth keeping for years, and why. A registry that swept up everything in var/
#: would grow without bound and bury the four reports anybody ever looks for.
KEPT = {
    "mutation-report.json": "which mutants were applied and which survived",
    "eval-report.json": "the assurance evaluation",
    "reference-eval.json": "the frozen reference set against the deployed corpus",
    "quality-report.json": "that ruff and mypy ran, with their exit codes",
    "load-probe.json": "latency and saturation with the conditions attached",
    "service-objectives.json": "what was promised, judged against what was measured",
    "chaos-matrix.json": "what the system said when each dependency was broken",
    "security/summary.json": "four scanners and their exit codes",
    "ingestion-recovery-drill.json": "an import killed three times and reconciled",
    "reproducible-build.json": "two builds compared, and the nondeterminism named",
    "retention-policy.json": "which retention clause was true when this was written",
    "accessibility-runtime.json": "WCAG 2.2 AA measured in the rendered page",
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "var")
    parser.add_argument("--into", type=Path, default=ROOT / "var/evidence")
    parser.add_argument(
        "--retain-years",
        type=int,
        default=10,
        help="the system's life, not the pipeline's; recorded, never used to delete here",
    )
    arguments = parser.parse_args()

    store = arguments.into / "objects"
    store.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    missing: list[str] = []
    for relative, why in sorted(KEPT.items()):
        source = arguments.source / relative
        if not source.is_file():
            # Named rather than skipped. A registry that silently omits what was not
            # produced reads as a complete record of a smaller system.
            missing.append(relative)
            continue
        digest = _digest(source)
        target = store / f"{digest}.json"
        if not target.exists():
            shutil.copy2(source, target)
            target.chmod(0o444)
        entries.append(
            {
                "report": relative,
                "why_kept": why,
                "sha256": digest,
                "bytes": source.stat().st_size,
                "captured_at": datetime.now(UTC).isoformat(),
                "object": f"objects/{digest}.json",
            }
        )

    body = {
        "schema_version": 1,
        "sealed_at": datetime.now(UTC).isoformat(),
        "retain_until": f"{datetime.now(UTC).year + arguments.retain_years}",
        "entries": entries,
        "not_produced": missing,
        "interpretation": (
            "Reports are copied under their digest, not referenced: a registry of paths "
            "is a registry of things that have since changed. The seal below is a digest "
            "over these entries — it catches a careless edit and does not stop a "
            "deliberate one, because anyone who can rewrite an entry can recompute it. "
            "What stops that is a signature with a key the editor does not hold."
        ),
    }
    seal = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    registry = {**body, "content_digest": seal}

    (arguments.into / "registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "entries": len(entries),
                "not_produced": missing,
                "content_digest": seal,
                "retain_until": registry["retain_until"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
