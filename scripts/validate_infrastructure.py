#!/usr/bin/env python3
"""Fail-closed static infrastructure contract validation.

The hundred checks this used to hold inline now live in
`korpus/infrastructure_requirements.py` as a register: each has an id, states its
property positively, and carries the reason it exists. This file loads the artefacts
and applies them.

The behaviour is unchanged. What changed is that a failure can be named — cited in an
audit, marked accepted-with-risk by an owner, matched to a mutant, counted — where
before it was a string appended at the point of failure, with no identity beyond its
own wording.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.requirements import (  # noqa: E402
    duplicate_ids,
    evaluate_requirements,
)
from korpus.infrastructure_requirements import (  # noqa: E402
    INFRASTRUCTURE_REQUIREMENTS,
    load_context,
)


def main() -> int:
    duplicates = duplicate_ids(INFRASTRUCTURE_REQUIREMENTS)
    if duplicates:
        # An id is how a requirement is cited. Two sharing one makes every reference to
        # it ambiguous, and the ambiguity is invisible in a passing run.
        print(json.dumps({"valid": False, "duplicate_requirement_ids": duplicates}, indent=2))
        return 1

    context = load_context(ROOT)
    report = evaluate_requirements(INFRASTRUCTURE_REQUIREMENTS, context)
    rendered = report.as_dict()
    rendered["services"] = sorted(context.services)
    if context.load_errors:
        rendered["load_errors"] = context.load_errors
    # The historic key, kept because `test_infrastructure_hardening.py` and the release
    # aggregator both read it, and a rename would be a second change riding on a
    # refactor that is meant to be behaviour-preserving.
    rendered["failures"] = [
        f"{failure['id']}: {failure['statement']}" for failure in rendered["failures"]
    ]

    output = ROOT / "var/infrastructure-validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rendered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rendered, ensure_ascii=False, indent=2))
    return 0 if report.satisfied else 1


if __name__ == "__main__":
    raise SystemExit(main())
