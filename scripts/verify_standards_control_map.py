#!/usr/bin/env python3
"""Verify that external-methodology mappings point to real local controls.

This is intentionally offline. It verifies the mapping substrate, not that external
standards pages still say what the engineering review recorded. Online source freshness is
a separate research activity and cannot be silently conflated with local PASS.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]

from korpus.application.provenance import compute_source_digest  # noqa: E402

from scripts.release_identity import release_tag  # noqa: E402

ALLOWED_REFERENCE_KINDS = {
    "normative-final",
    "normative-stable",
    "normative-approved",
    "draft-informative",
    "industry-methodology",
    "research",
}
ALLOWED_LOCAL_STATUS = {"EXECUTABLE", "EXTERNAL_REQUIRED", "INFORMATIVE"}


def _valid_https(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _verify_references(references: list[object]) -> tuple[list[str], set[str]]:
    failures: list[str] = []
    ids: set[str] = set()
    for index, item in enumerate(references):
        if not isinstance(item, dict):
            failures.append(f"reference[{index}].shape")
            continue
        ref_id = item.get("id")
        if not isinstance(ref_id, str) or not ref_id or ref_id in ids:
            failures.append(f"reference[{index}].id")
        else:
            ids.add(ref_id)
        if item.get("kind") not in ALLOWED_REFERENCE_KINDS:
            failures.append(f"reference[{index}].kind")
        if not _valid_https(item.get("url")):
            failures.append(f"reference[{index}].url")
    return failures, ids


def _control_evidence_failures(root: Path, index: int, evidence: object) -> list[str]:
    if not isinstance(evidence, list) or not evidence:
        return [f"control[{index}].evidence"]
    return [
        f"control[{index}].missing_evidence:{relative}"
        for relative in evidence
        if not isinstance(relative, str) or not (root / relative).is_file()
    ]


def _control_reference_failures(index: int, refs: object, known: set[str]) -> list[str]:
    if not isinstance(refs, list) or not refs:
        return [f"control[{index}].references"]
    return [f"control[{index}].unknown_reference:{ref}" for ref in refs if ref not in known]


def _verify_controls(
    root: Path, controls: list[object], known_references: set[str]
) -> tuple[list[str], int, int]:
    failures: list[str] = []
    ids: set[str] = set()
    executable = external = 0
    for index, item in enumerate(controls):
        if not isinstance(item, dict):
            failures.append(f"control[{index}].shape")
            continue
        control_id = item.get("id")
        if not isinstance(control_id, str) or not control_id or control_id in ids:
            failures.append(f"control[{index}].id")
        else:
            ids.add(control_id)
        status = item.get("local_status")
        if status not in ALLOWED_LOCAL_STATUS:
            failures.append(f"control[{index}].local_status")
        executable += int(status == "EXECUTABLE")
        external += int(status == "EXTERNAL_REQUIRED")
        failures.extend(
            _control_reference_failures(index, item.get("references"), known_references)
        )
        failures.extend(_control_evidence_failures(root, index, item.get("evidence")))
    return failures, executable, external


def _draft_classification_failure(references: list[object]) -> list[str]:
    item = next(
        (
            value
            for value in references
            if isinstance(value, dict) and value.get("id") == "NIST-SSDF-1.2-DRAFT"
        ),
        None,
    )
    return (
        []
        if item is not None and item.get("kind") == "draft-informative"
        else ["nist_ssdf_1_2_must_remain_draft_informative"]
    )


def verify(root: Path, config: Path) -> dict[str, object]:
    data = json.loads(config.read_text(encoding="utf-8"))
    failures = [] if data.get("schema") == "korpus.standards-control-map.v1" else ["schema"]
    references, controls = data.get("references"), data.get("controls")
    if not isinstance(references, list) or not isinstance(controls, list):
        return {"status": "FAIL", "failures": [*failures, "shape"]}

    reference_failures, reference_ids = _verify_references(references)
    control_failures, executable, external = _verify_controls(root, controls, reference_ids)
    failures.extend(reference_failures)
    failures.extend(control_failures)
    failures.extend(_draft_classification_failure(references))
    return {
        "schema": "korpus.standards-control-map-verification.v2",
        "status": "PASS" if not failures else "FAIL",
        "release": release_tag(),
        "source_tree_sha256": compute_source_digest(root),
        "references": len(references),
        "controls": len(controls),
        "executable_controls": executable,
        "external_required_controls": external,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--config", type=Path, default=Path("config/assurance/standards-control-map.v1.json")
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    config = args.config if args.config.is_absolute() else root / args.config
    result = verify(root, config)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = args.out if args.out.is_absolute() else root / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
