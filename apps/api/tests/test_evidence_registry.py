"""Cited evidence must resolve to something that can fail.

Destruction stage 2026-08-03: the closure builder accepted any non-empty evidence
list. It never opened the files. A finding could cite a deleted test and read
CLOSED forever.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from korpus.application.evidence_registry import (
    is_executable_evidence,
    split_reference,
    verify_closure_registry,
    verify_references,
)

ROOT = Path(__file__).resolve().parents[3]
CLOSURE_BUILDER = ROOT / "scripts/build_audit_closure.py"


def _registry() -> tuple[dict[str, list[str]], dict[str, str]]:
    """Read EVIDENCE and the status sets out of the builder without importing it."""

    tree = ast.parse(CLOSURE_BUILDER.read_text(encoding="utf-8"))
    evidence: dict[str, list[str]] = {}
    sets: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "EVIDENCE":
            evidence = ast.literal_eval(node.value)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            name = getattr(target, "id", "")
            if name in {"CLOSED_LOCAL", "MITIGATED_LOCAL", "EXTERNAL_DEBT", "OPEN_TECH_DEBT"}:
                sets[name] = set(ast.literal_eval(node.value))
    statuses = {
        finding: status for status, members in sets.items() for finding in members
    }
    assert evidence and statuses, "the closure registry could not be read"
    return evidence, statuses


def test_the_shipped_registry_cites_only_evidence_that_exists() -> None:
    evidence, statuses = _registry()
    assert verify_closure_registry(ROOT, evidence, statuses) == []


def test_a_missing_file_is_reported() -> None:
    problems = verify_references(ROOT, ["apps/api/tests/test_does_not_exist.py"])
    assert problems and "does not exist" in problems[0]


def test_a_deleted_test_inside_an_existing_file_is_reported() -> None:
    """The exact failure the counter could not see: file present, test gone."""

    problems = verify_references(
        ROOT, ["apps/api/tests/test_evidence_registry.py::test_removed_last_year"]
    )
    assert problems and "not defined" in problems[0]


def test_a_present_test_resolves() -> None:
    assert (
        verify_references(
            ROOT,
            [
                "apps/api/tests/test_evidence_registry.py::test_a_present_test_resolves",
                "apps/api/tests/test_evidence_registry.py",
            ],
        )
        == []
    )


def test_parametrized_citations_resolve_to_their_base_name() -> None:
    assert split_reference("a/b.py::test_x[case-1]") == ("a/b.py", "test_x")
    assert split_reference("a/b.py") == ("a/b.py", None)


def test_a_ci_job_citation_resolves_against_the_pipeline() -> None:
    assert verify_references(ROOT, [".gitlab-ci.yml::api:test"]) == []
    problems = verify_references(ROOT, [".gitlab-ci.yml::api:job-that-never-existed"])
    assert problems and "CI job does not exist" in problems[0]


def test_a_selector_on_a_non_test_file_is_refused() -> None:
    problems = verify_references(ROOT, ["Makefile::api-test"])
    assert problems and "cited by selector" in problems[0]


def test_a_directory_citation_is_accepted() -> None:
    assert verify_references(ROOT, ["deploy/kubernetes"]) == []


@pytest.mark.parametrize(
    "reference,executable",
    [
        ("apps/api/tests/test_x.py::test_y", True),
        ("apps/api/tests/test_x.py", True),
        (".gitlab-ci.yml::api:test", True),
        (".gitlab-ci.yml", False),
        ("docs/governance/RISK_REGISTER.md", False),
        ("apps/api/src/korpus/main.py", False),
    ],
)
def test_only_a_test_or_a_ci_job_counts_as_executable(reference: str, executable: bool) -> None:
    assert is_executable_evidence(reference) is executable


def test_closure_claimed_on_prose_alone_is_rejected() -> None:
    problems = verify_closure_registry(
        ROOT,
        {"XYZ-001": ["docs/governance/RISK_REGISTER.md"]},
        {"XYZ-001": "CLOSED_LOCAL"},
    )
    assert problems and "no test or CI job" in problems[0]


def test_a_mitigated_finding_may_rest_on_documents() -> None:
    """MITIGATED is a weaker claim than CLOSED and does not require a failing test."""

    assert (
        verify_closure_registry(
            ROOT,
            {"XYZ-002": ["docs/governance/RISK_REGISTER.md"]},
            {"XYZ-002": "MITIGATED_LOCAL"},
        )
        == []
    )
