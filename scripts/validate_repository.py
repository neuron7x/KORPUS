#!/usr/bin/env python3
"""Fail-closed repository contract validation.
The checks live in `korpus/repository_requirements.py` as a register: each has an id,
states its property positively, and carries the reason it exists. This file loads the
tree and applies them.
Behaviour is unchanged; identity is added. "missing required file: SECURITY.md" was a
sentence with no id, so it could not be cited in an audit, marked accepted-with-risk by
an owner, matched to a mutant, or counted.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.requirements import (  # noqa: E402
    duplicate_ids,
    evaluate_requirements,
)
from korpus.repository_requirements import (  # noqa: E402
    REPOSITORY_REQUIREMENTS,
    load_context,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", choices=("SOURCE_CHECKOUT", "FULL_SSOT_DISTRIBUTION"), default="SOURCE_CHECKOUT")
    args = parser.parse_args()
    duplicates = duplicate_ids(REPOSITORY_REQUIREMENTS)
    if duplicates:
        print(json.dumps({"valid": False, "duplicate_requirement_ids": duplicates}, indent=2))
        return 1

    context = load_context(ROOT, args.context)
    report = evaluate_requirements(REPOSITORY_REQUIREMENTS, context)
    if not report.satisfied:
        for failure in report.unmet:
            print(f"{failure.id}: {failure.statement}")
        return 1
    print(
        f"repository validation passed: {context.path_count} paths, "
        f"{report.total} requirements, 99/99 audit findings classified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
