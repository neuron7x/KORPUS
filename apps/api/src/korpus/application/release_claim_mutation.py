from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from korpus.application.release_claim_admission import canonical_paths_admitted
from korpus.application.release_claim_common import (
    EvidenceContext,
    integer,
    provenance_generated_by,
)
from korpus.application.release_claim_hosted_contract import hosted_execution_admitted


@dataclass(frozen=True)
class MutantSpec:
    file: str
    tests: tuple[str, ...]
    full_copy: bool


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.IfExp) and isinstance(node.test, ast.Constant):
        return _constant_string(node.body if node.test.value else node.orelse)
    return None


def _literal_strings(node: ast.AST) -> tuple[str, ...] | None:
    if not isinstance(node, ast.Tuple):
        return None
    values = [_constant_string(item) for item in node.elts]
    return (
        None if any(item is None for item in values) else tuple(cast(str, item) for item in values)
    )


def _mutant_spec(call: ast.AST) -> tuple[str, MutantSpec] | None:
    if not isinstance(call, ast.Call) or len(call.args) < 5:
        return None
    raw_id, raw_file, raw_tests = call.args[0], call.args[1], call.args[4]
    if not isinstance(raw_id, ast.Constant) or not isinstance(raw_id.value, str):
        return None
    if not isinstance(raw_file, ast.Constant) or not isinstance(raw_file.value, str):
        return None
    tests = _literal_strings(raw_tests)
    if not tests:
        return None
    full_copy = any(
        keyword.arg == "full_copy"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in call.keywords
    )
    return raw_id.value, MutantSpec(raw_file.value, tests, full_copy)


def _catalogue(root: Path) -> dict[str, MutantSpec] | None:
    try:
        tree = ast.parse((root / "scripts/run_mutation_tests.py").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return None
    assignment = next(
        (
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "MUTANTS" for target in node.targets
            )
        ),
        None,
    )
    if not isinstance(assignment, ast.Tuple):
        return None
    parsed = [_mutant_spec(item) for item in assignment.elts]
    if any(item is None for item in parsed):
        return None
    entries = [item for item in parsed if item is not None]
    catalogue = dict(entries)
    return catalogue if len(catalogue) == len(entries) and catalogue else None


def _result_valid(result: object, identifier: str, spec: MutantSpec) -> bool:
    if not isinstance(result, dict):
        return False
    overlay = spec.file.startswith("apps/api/src/") and not spec.full_copy
    expected = {
        "id": identifier,
        "file": spec.file,
        "status": "KILLED",
        "returncode": 1,
        "target_occurrences": 1,
        "tests": list(spec.tests),
        "sandbox_mode": "api_source_overlay" if overlay else "full_copy",
    }
    return all(result.get(key) == value for key, value in expected.items())


def _inputs(catalogue: dict[str, MutantSpec]) -> list[str]:
    paths = {
        "reports/MUTATION_REPORT.json",
        "scripts/run_mutation_tests.py",
        *(spec.file for spec in catalogue.values()),
        *(test.split("::", 1)[0] for spec in catalogue.values() for test in spec.tests),
    }
    return sorted(paths)


def mutation_evidence(payload: dict[str, Any], context: EvidenceContext) -> bool:
    alias = context.root / "reports/MUTATION_REPORT.json"
    try:
        aliases_equal = alias.is_file() and alias.read_bytes() == context.path.read_bytes()
    except OSError:
        return False
    catalogue, results = _catalogue(context.root), payload.get("results")
    if catalogue is None or not isinstance(results, list) or not aliases_equal:
        return False
    indexed = {str(result.get("id")): result for result in results if isinstance(result, dict)}
    complete = len(indexed) == len(results) == len(catalogue) and set(indexed) == set(catalogue)
    if not complete or not all(
        _result_valid(indexed[identifier], identifier, spec)
        for identifier, spec in catalogue.items()
    ):
        return False
    count = len(catalogue)
    valid = (
        canonical_paths_admitted(context.root, _inputs(catalogue))
        and payload.get("schema_version") == 3
        and payload.get("status") == "PASS"
        and payload.get("shard_index") is None
        and integer(payload.get("shard_count"), minimum=1)
        and payload.get("mutants") == count
        and payload.get("valid_mutants") == count
        and payload.get("killed") == count
        and payload.get("survived") == payload.get("invalid") == payload.get("errors") == []
        and payload.get("mutation_score") == 1.0
        and payload.get("mutation_score_over_catalogue") == 1.0
        and provenance_generated_by(payload, "scripts/run_mutation_tests.py")
    )
    result = {
        "mutants": payload.get("mutants"),
        "killed": payload.get("killed"),
        "survived": payload.get("survived"),
        "invalid": payload.get("invalid"),
        "errors": payload.get("errors"),
        "mutation_score": payload.get("mutation_score"),
    }
    return valid and hosted_execution_admitted(
        context,
        [context.evidence, "reports/MUTATION_REPORT.json"],
        result,
    )
