#!/usr/bin/env python3
"""Validate every applyable Kubernetes variant, not just the base directory.

Until 2026-08-04 this script globbed ``deploy/kubernetes/base/*.yaml``. The
production overlay was never rendered, so its patches were outside every gate:
a patch setting ``image: …:latest`` with ``readOnlyRootFilesystem: false`` passed
validation (destruction stage 2026-08-03). Overlays are now discovered, rendered
and validated — and a variant that exists but cannot be rendered is a failure,
not a directory the gate quietly skips.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.deployment import (  # noqa: E402  (path set above)
    RenderError,
    discover_kustomizations,
    manifest_violations,
    render_kustomization,
)
from korpus.application.provenance import PROVENANCE_KEY, stamp  # noqa: E402

DEPLOY_ROOT = ROOT / "deploy/kubernetes"


def main() -> int:
    variants = discover_kustomizations(DEPLOY_ROOT)
    if not variants:
        print(json.dumps({"status": "FAIL", "reason": "no kustomization found"}, indent=2))
        return 1

    results: dict[str, object] = {}
    failed = False
    for directory in variants:
        name = directory.relative_to(DEPLOY_ROOT).as_posix() or "base"
        try:
            documents = render_kustomization(directory, ROOT)
        except RenderError as error:
            results[name] = {"status": "FAIL", "violations": [f"render error: {error}"]}
            failed = True
            continue
        violations = manifest_violations(documents)
        results[name] = {
            "status": "PASS" if not violations else "FAIL",
            "resources": len(documents),
            "violations": violations,
        }
        failed = failed or bool(violations)

    report = {
        "status": "FAIL" if failed else "PASS",
        "variants": results,
        "note": "static topology validation only; cluster execution remains external evidence",
        PROVENANCE_KEY: stamp(ROOT, "scripts/validate_kubernetes.py"),
    }
    output = ROOT / "var/kubernetes-validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    visible = {key: value for key, value in report.items() if key != PROVENANCE_KEY}
    print(json.dumps(visible, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
