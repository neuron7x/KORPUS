from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_MUTATION_RESULT_KEYS = (
    "id",
    "file",
    "status",
    "returncode",
    "target_occurrences",
    "tests",
    "sandbox_mode",
)
_MUTATION_SUMMARY_KEYS = (
    "schema_version",
    "status",
    "release",
    "shard_index",
    "shard_count",
    "mutants",
    "valid_mutants",
    "killed",
    "survived",
    "invalid",
    "errors",
    "mutation_score",
    "mutation_score_over_catalogue",
)

COMPANIONS = {
    "INFERENCE_SECURITY_GATE.junit.xml": (
        "INFERENCE_SECURITY_GATE.json",
        "var/production/inference_security.pytest.xml",
        "junit_sha256",
    ),
    "WEB_REGRESSION_REPORT.tap": (
        "WEB_REGRESSION_REPORT.json",
        "var/web-regression.tap",
        "test_output_sha256",
    ),
}


def mutation_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("mutation execution has no results")
    projected: list[dict[str, Any]] = []
    for entry in results:
        if not isinstance(entry, Mapping):
            raise ValueError("mutation result is not an object")
        projected.append({key: entry.get(key) for key in _MUTATION_RESULT_KEYS})
    provenance = payload.get("provenance")
    stable_provenance = (
        {key: value for key, value in provenance.items() if key != "generated_at"}
        if isinstance(provenance, Mapping)
        else provenance
    )
    return {
        **{key: payload.get(key) for key in _MUTATION_SUMMARY_KEYS},
        "provenance": stable_provenance,
        "results": projected,
    }


def inference_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in payload.items() if key not in {"junit_sha256", "output_tail"}
    }


def stable_web(payload: Mapping[str, Any]) -> dict[str, Any]:
    provenance = payload.get("provenance")
    normalized = dict(payload)
    normalized.pop("test_output_sha256", None)
    if isinstance(provenance, Mapping):
        normalized["provenance"] = {
            key: value for key, value in provenance.items() if key != "generated_at"
        }
    return normalized


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _nonempty_string_list(value: object) -> bool:
    return bool(
        isinstance(value, list) and value and all(isinstance(item, str) and item for item in value)
    )


def _mutation_result_valid(entry: object) -> bool:
    if not isinstance(entry, Mapping):
        return False
    return bool(
        entry.get("status") == "KILLED"
        and _nonempty_string(entry.get("id"))
        and _nonempty_string(entry.get("file"))
        and _nonempty_string(entry.get("sandbox_mode"))
        and isinstance(entry.get("returncode"), int)
        and not isinstance(entry["returncode"], bool)
        and entry["returncode"] != 0
        and _positive_int(entry.get("target_occurrences"))
        and _nonempty_string_list(entry.get("tests"))
    )


def _perfect_score(value: object) -> bool:
    return type(value) is float and value == 1.0


def _unique_mutation_ids(entries: list[object]) -> bool:
    ids = {entry.get("id") for entry in entries if isinstance(entry, Mapping)}
    return len(ids) == len(entries)


def _exact_json(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return actual.keys() == expected.keys() and all(
            _exact_json(actual[key], value) for key, value in expected.items()
        )
    return actual == expected


def mutation_execution_valid(payload: Mapping[str, Any]) -> bool:
    results = payload.get("results")
    counts = (payload.get("mutants"), payload.get("valid_mutants"), payload.get("killed"))
    empty = (payload.get("survived"), payload.get("invalid"), payload.get("errors"))
    return bool(
        isinstance(results, list)
        and results
        and payload.get("schema_version") == 3
        and payload.get("status") == "PASS"
        and _nonempty_string(payload.get("release"))
        and payload.get("shard_index") is None
        and _positive_int(payload.get("shard_count"))
        and all(_positive_int(value) for value in counts)
        and counts == (len(results),) * 3
        and empty == ([], [], [])
        and _perfect_score(payload.get("mutation_score"))
        and _perfect_score(payload.get("mutation_score_over_catalogue"))
        and all(_mutation_result_valid(entry) for entry in results)
        and _unique_mutation_ids(results)
    )


def web_execution_valid(
    payload: Mapping[str, Any], release: str, counts: Mapping[str, int], digest: str
) -> bool:
    step = {"exit_code": 0, "status": "PASS"}
    expected_steps = {"lint": step, "test": {**step, **counts}, "build": step}
    expected_totals = {
        "tests": counts["tests"],
        "passed": counts["pass"],
        "failed": counts["fail"],
        "skipped": counts["skipped"],
    }
    return bool(
        payload.get("schema") == "korpus.web-regression.v1"
        and payload.get("evidence_class") == "LOCAL_NODE_TEST_RUNNER"
        and payload.get("status") == "PASS"
        and payload.get("release") == release
        and payload.get("test_output_sha256") == digest
        and _exact_json(payload.get("steps"), expected_steps)
        and all(_exact_json(payload.get(key), value) for key, value in expected_totals.items())
    )


def publish_companion(
    destination: Path, report_path: Path, source_path: Path, digest_field: str
) -> str | None:
    destination.unlink(missing_ok=True)
    if not report_path.is_file() or not source_path.is_file():
        return "report or exact execution companion is absent"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "report is not valid JSON"
    if not isinstance(report, dict):
        return "report is not a JSON object"
    payload = source_path.read_bytes()
    if report.get(digest_field) != hashlib.sha256(payload).hexdigest():
        return f"{digest_field} does not bind the exact execution companion"
    shutil.copyfile(source_path, destination)
    return None


def publish_execution_companions(
    root: Path,
    destination: Path,
    published: list[str],
    refused: list[dict[str, str]],
) -> None:
    for name, (report_name, relative, digest_field) in COMPANIONS.items():
        if report_name not in published:
            refused.append({"report": name, "reason": f"{report_name} was not admitted"})
            continue
        reason = publish_companion(
            destination / name,
            destination / report_name,
            root / relative,
            digest_field,
        )
        if reason is not None:
            refused.append({"report": name, "reason": reason})
            continue
        published.append(name)
