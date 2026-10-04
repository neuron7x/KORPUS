#!/usr/bin/env python3
"""Verify audit closure using local scanner evidence without writing canonical files."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from audit_closure_evidence import evidence_for_run  # noqa: E402
from audit_closure_validation import validate_registry  # noqa: E402
from audit_scanner_summary import validate_selected_security_summary  # noqa: E402
from build_audit_closure import (  # noqa: E402
    CLASSIFICATION,
    EVIDENCE,
    SOURCE,
)


def main() -> None:
    selection = evidence_for_run(EVIDENCE, local_security_summary=True)
    binding = validate_selected_security_summary(ROOT, selection)
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    findings, statuses = validate_registry(ROOT, source, selection.references, CLASSIFICATION)
    counts = Counter(statuses.values())
    print(
        json.dumps(
            {
                "schema": "korpus.audit-closure-local.v1",
                "status": "PASS",
                "source_release": source["release"],
                "findings": len(findings),
                "counts": dict(sorted(counts.items())),
                "produced_evidence": {**selection.metadata, **binding.metadata},
                "canonical_outputs_written": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
