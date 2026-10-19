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
