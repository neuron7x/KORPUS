"""Cited evidence must resolve to something that can fail.

Destruction stage 2026-08-03: the closure builder accepted any non-empty evidence
list. It never opened the files. A finding could cite a deleted test and read
CLOSED forever.
"""

from __future__ import annotations

import ast
import json
import sys
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
sys.path.insert(0, str(ROOT / "scripts"))
import audit_scanner_summary as scanner_summary  # noqa: E402
from audit_closure_evidence import (  # noqa: E402
    CI_SECURITY_SUMMARY,
    LOCAL_SECURITY_SUMMARY,
    evidence_for_run,
)
from build_audit_closure import EVIDENCE  # noqa: E402


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
    statuses = {finding: status for status, members in sets.items() for finding in members}
    assert evidence and statuses, "the closure registry could not be read"
    return evidence, statuses


def test_the_shipped_registry_cites_only_evidence_that_exists() -> None:
    """Tree citations only: this test runs in `api:test`, before anything produces var/.

    It used to check produced artefacts too and passed on every developer machine,
    because an earlier `make mutation` had left var/mutation-report.json behind. In
    CI it failed — but only once `repository:validate` stopped failing earlier and
    let `api:test` run at all (2026-08-05, pipeline #37). That a produced artefact
    has a producer, and that whoever resolves it runs after it, is asserted in
    test_gate_parity.py; here it would only assert that someone had run make.
    """
    evidence, statuses = _registry()
    assert verify_closure_registry(ROOT, evidence, statuses, include_produced=False) == []


def test_local_closure_substitutes_only_the_scanner_evidence_class() -> None:
    ci = evidence_for_run(EVIDENCE, local_security_summary=False).references
    local_selection = evidence_for_run(EVIDENCE, local_security_summary=True)
    local = local_selection.references
    assert CI_SECURITY_SUMMARY in ci["SUP-005"]
    assert LOCAL_SECURITY_SUMMARY not in ci["SUP-005"]
    assert LOCAL_SECURITY_SUMMARY in local["SUP-005"]
    assert CI_SECURITY_SUMMARY not in local["SUP-005"]
    assert local_selection.metadata == {
        "security_summary": LOCAL_SECURITY_SUMMARY,
        "security_summary_class": "LOCAL_SCANNERS",
    }
    assert {key: value for key, value in ci.items() if key != "SUP-005"} == {
        key: value for key, value in local.items() if key != "SUP-005"
    }


@pytest.mark.parametrize(
    "scanner_references",
    [
        ["scripts/security_scan.sh"],
        [CI_SECURITY_SUMMARY, CI_SECURITY_SUMMARY],
        [CI_SECURITY_SUMMARY, LOCAL_SECURITY_SUMMARY],
    ],
)
def test_scanner_evidence_class_drift_fails_closed(scanner_references: list[str]) -> None:
    source = {**EVIDENCE, "SUP-005": scanner_references}
    with pytest.raises(RuntimeError):
        evidence_for_run(source, local_security_summary=True)


def _local_scanner_summary(commit: str = "a" * 40) -> dict[str, object]:
    return {
        "schema_version": 1,
        "class": "LOCAL_SCANNERS",
        "commit_sha": commit,
        "status": "PASS",
        "worst_exit_code": 0,
        "scanners": [
            {"scanner": name, "exit_code": 0} for name in sorted(scanner_summary.EXPECTED_SCANNERS)
        ],
    }


def test_scanner_summary_is_bound_to_the_current_source(tmp_path, monkeypatch) -> None:
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(_local_scanner_summary()), encoding="utf-8")
    monkeypatch.setattr(
        scanner_summary,
        "source_tree_digest",
        lambda ref: "current" if ref == "HEAD" else "stale",
    )

    with pytest.raises(RuntimeError, match="different source tree"):
        scanner_summary.validate_security_summary(tmp_path, "summary.json", "LOCAL_SCANNERS")


def test_current_complete_scanner_summary_carries_its_binding(tmp_path, monkeypatch) -> None:
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(_local_scanner_summary()), encoding="utf-8")
    monkeypatch.setattr(scanner_summary, "source_tree_digest", lambda _ref: "same")

    binding = scanner_summary.validate_security_summary(tmp_path, "summary.json", "LOCAL_SCANNERS")

    assert binding.metadata == {
        "security_summary_commit": "a" * 40,
        "security_summary_source_tree_sha256": "same",
        "security_summary_scanners": 4,
    }


@pytest.mark.parametrize(
    ("poison", "message"),
    [
        ({"status": "FAIL"}, "verdict"),
        ({"worst_exit_code": 1}, "verdict"),
        ({"class": "PINNED_CI_SCANNERS"}, "evidence class"),
        ({"scanners": []}, "scanner set"),
    ],
)
def test_scanner_summary_refuses_false_or_incomplete_success(
    tmp_path, monkeypatch, poison: dict[str, object], message: str
) -> None:
    payload = {**_local_scanner_summary(), **poison}
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(scanner_summary, "source_tree_digest", lambda _ref: "same")

    with pytest.raises(RuntimeError, match=message):
        scanner_summary.validate_security_summary(tmp_path, "summary.json", "LOCAL_SCANNERS")


def test_gitlab_scanner_summary_cannot_claim_canonical_ci_evidence(tmp_path, monkeypatch) -> None:
    path = tmp_path / "summary.json"
    payload = {
        "schema_version": 2,
        "provider": "gitlab-ci",
        "commit_sha": "a" * 40,
        "status": "PASS",
        "worst_exit_code": 0,
        "checks": dict.fromkeys(scanner_summary.CI_CHECKS, True),
        "failures": [],
        "scanners": [
            {"scanner": name, "exit_code": 0} for name in sorted(scanner_summary.EXPECTED_SCANNERS)
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(scanner_summary, "source_tree_digest", lambda _ref: "same")

    with pytest.raises(RuntimeError, match="canonical GitHub Actions"):
        scanner_summary.validate_security_summary(tmp_path, "summary.json", "PINNED_CI_SCANNERS")


def test_both_closure_executors_validate_the_scanner_payload() -> None:
    for relative in ("scripts/verify_audit_closure_local.py", "scripts/build_audit_closure.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "binding = validate_selected_security_summary(ROOT, selection)" in source


def test_a_produced_artifact_is_still_checked_when_the_caller_runs_after_its_producer() -> None:
    """The relaxation is scoped: with the flag on, a missing produced file is reported.

    build_audit_closure.py runs in `audit:closure`, after api:assurance, and calls
    with the default. If that path stopped reporting, COD-005 would cite a mutation
    report nobody produced and the registry would read closed.
    """
    problems = verify_closure_registry(
        ROOT,
        {"COD-005": ["var/does-not-exist-report.json"]},
        {"COD-005": "MITIGATED_LOCAL"},
    )
    assert problems and "does not exist" in problems[0]
    assert (
        verify_closure_registry(
            ROOT,
            {"COD-005": ["var/does-not-exist-report.json"]},
            {"COD-005": "MITIGATED_LOCAL"},
            include_produced=False,
        )
        == []
    )


def test_the_relaxation_cannot_excuse_a_missing_test() -> None:
    """include_produced=False must not become a way to skip tree evidence."""
    problems = verify_closure_registry(
        ROOT,
        {"COD-005": ["apps/api/tests/test_does_not_exist.py"]},
        {"COD-005": "MITIGATED_LOCAL"},
        include_produced=False,
    )
    assert problems and "does not exist" in problems[0]


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


def test_a_ci_job_citation_resolves_against_the_canonical_workflow() -> None:
    assert verify_references(ROOT, [".github/workflows/ci.yml::api-test"]) == []
    problems = verify_references(ROOT, [".github/workflows/ci.yml::job-that-never-existed"])
    assert problems and "GitHub Actions job does not exist" in problems[0]


def test_the_historical_gitlab_pipeline_is_not_executable_closure_authority() -> None:
    reference = ".gitlab-ci.yml::api:test"
    assert is_executable_evidence(reference) is False
    problems = verify_references(ROOT, [reference])
    assert problems and "only .py tests and GitHub Actions jobs" in problems[0]


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
        (".github/workflows/ci.yml::api-test", True),
        (".github/workflows/ci.yml", False),
        (".gitlab-ci.yml::api:test", False),
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


def test_the_tracked_closure_register_carries_no_run_binding(tmp_path) -> None:
    """Трекований звіт не може назвати коміт, на якому його зібрано.

    10.10.2026 `source:package` уперше в історії добіг — і впав на «source digest
    mismatch»: `audit:closure` дописував у трекований JSON `produced_evidence` з комітом
    сканерів, тож файл розходився з маніфестом джерела в кожному конвеєрі за побудовою.
    """
    tracked = json.loads(
        (ROOT / "docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json").read_text("utf-8")
    )
    assert "produced_evidence" not in tracked
    builder = (ROOT / "scripts/build_audit_closure.py").read_text(encoding="utf-8")
    assert '"produced_evidence"' not in builder

    written = scanner_summary.write_run_binding(tmp_path, {"security_summary_commit": "a" * 40})
    assert written == tmp_path / scanner_summary.RUN_BINDING
    assert json.loads(written.read_text("utf-8")) == {"security_summary_commit": "a" * 40}
    assert not scanner_summary.RUN_BINDING.startswith(("docs/", "reports/"))
