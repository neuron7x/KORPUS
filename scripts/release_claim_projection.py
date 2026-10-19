from __future__ import annotations

from collections.abc import Mapping
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
