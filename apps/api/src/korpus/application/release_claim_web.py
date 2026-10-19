from __future__ import annotations

import re
from typing import Any, cast

from korpus.application.release_claim_admission import canonical_paths_admitted
from korpus.application.release_claim_common import (
    EvidenceContext,
    file_sha256,
    integer,
    provenance_generated_by,
)
from korpus.application.release_claim_hosted_contract import hosted_execution_admitted


def _tap_counts(text: str) -> dict[str, int] | None:
    found: dict[str, int] = {}
    for key in ("tests", "pass", "fail", "skipped"):
        match = re.search(rf"^# {key} (\d+)$", text, re.MULTILINE)
        if match:
            found[key] = int(match.group(1))
    return found if set(found) == {"tests", "pass", "fail", "skipped"} else None


def _steps_valid(steps: dict[str, Any], payload: dict[str, Any]) -> bool:
    for name in ("lint", "test", "build"):
        step = steps.get(name)
        if not isinstance(step, dict) or step.get("status") != "PASS" or step.get("exit_code") != 0:
            return False
    test = steps["test"]
    fields = ("tests", "pass", "fail", "skipped")
    if not all(integer(test.get(field), minimum=1 if field == "tests" else 0) for field in fields):
        return False
    tests, passed, failed, skipped = (cast(int, test[field]) for field in fields)
    return (
        tests == passed + failed + skipped
        and failed == 0
        and payload.get("tests") == tests
        and payload.get("passed") == passed
        and payload.get("failed") == failed
        and payload.get("skipped") == skipped
    )


def web_evidence(payload: dict[str, Any], context: EvidenceContext) -> bool:
    steps = payload.get("steps")
    tap_relative = f"reports/release/{context.release}/WEB_REGRESSION_REPORT.tap"
    tap_path = context.root / tap_relative
    try:
        tap_counts = _tap_counts(tap_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return False
    if tap_counts is None:
        return False
    if (
        payload.get("schema") != "korpus.web-regression.v1"
        or payload.get("status") != "PASS"
        or payload.get("evidence_class") != "LOCAL_NODE_TEST_RUNNER"
        or not provenance_generated_by(payload, "scripts/publish_web_regression.py")
        or payload.get("test_output_sha256") != file_sha256(tap_path)
        or not canonical_paths_admitted(
            context.root,
            ["apps/web/package.json", "scripts/publish_web_regression.py", tap_relative],
        )
        or not isinstance(steps, dict)
        or set(steps) != {"lint", "test", "build"}
        or not isinstance(steps.get("test"), dict)
        or any(steps["test"].get(key) != value for key, value in tap_counts.items())
    ):
        return False
    result = {
        "tests": payload.get("tests"),
        "pass": payload.get("passed"),
        "fail": payload.get("failed"),
        "skipped": payload.get("skipped"),
    }
    return _steps_valid(steps, payload) and hosted_execution_admitted(
        context, [context.evidence, tap_relative], result
    )
