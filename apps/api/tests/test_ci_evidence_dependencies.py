"""Executable contract for the current-run CI producer/consumer graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _workflow(name: str) -> dict[str, Any]:
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())


def _artifact_step(steps: list[dict[str, Any]], action: str, name: str) -> dict[str, Any]:
    matches = [
        step
        for step in steps
        if step.get("uses", "").startswith(f"actions/{action}@")
        and step.get("with", {}).get("name") == name + "-${{ github.run_attempt }}"
    ]
    assert len(matches) == 1, (action, name, matches)
    return matches[0]


def test_ci_invokes_the_same_commit_producers_before_consumers() -> None:
    ci, assurance = _workflow("ci.yml"), _workflow("assurance.yml")
    assert ci["jobs"]["assurance"]["uses"] == "./.github/workflows/assurance.yml"
    triggers = assurance.get("on", assurance.get(True))
    assert "workflow_call" in triggers
    assert "workflow_dispatch" in triggers and "schedule" in triggers
    assert "pull_request" not in triggers and "push" not in triggers
    for name in ("api-test", "repository"):
        job = ci["jobs"][name]
        needs = job["needs"]
        assert "assurance" in ([needs] if isinstance(needs, str) else needs)
        assert "if" not in job and job.get("continue-on-error") is not True


def test_required_artifacts_have_complete_inputs_and_current_run_downloads() -> None:
    ci, assurance = _workflow("ci.yml"), _workflow("assurance.yml")
    contracts = (
        (
            "postgres",
            "api-test",
            "coverage-postgres",
            "make coverage-ratchet",
            {"coverage-postgres.json", "coverage-postgres.data", "coverage-postgres-receipt.json"},
        ),
        (
            "research-assurance",
            "repository",
            "source-assurance",
            "make validate",
            {
                "eval-report.json",
                "mutation-report.json",
                "migration-report.json",
                "scale-report.json",
                "operational-gate.json",
            },
        ),
    )
    for producer, consumer, name, command, filenames in contracts:
        upload = _artifact_step(assurance["jobs"][producer]["steps"], "upload-artifact", name)
        assert upload.get("if", "success()") == "success()"
        assert upload["with"]["if-no-files-found"] == "error"
        assert set(upload["with"]["path"].splitlines()) == {f"var/{item}" for item in filenames}
        steps = ci["jobs"][consumer]["steps"]
        download = _artifact_step(steps, "download-artifact", name)
        assert download["with"] == {"name": name + "-${{ github.run_attempt }}", "path": "var"}
        command_indexes = [i for i, step in enumerate(steps) if command in step.get("run", "")]
        assert len(command_indexes) == 1
        assert steps.index(download) < command_indexes[0]


def test_postgres_publishes_measured_coverage_and_retains_security_gate() -> None:
    steps = _workflow("assurance.yml")["jobs"]["postgres"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps)
    assert "scripts/run_postgres_coverage.sh" in commands
    assert "make production-postgres-security PY=python" in commands
    assert "missing or empty required coverage output" in commands
    assert "scripts/run_postgres_suite.sh" not in commands


def test_producer_and_consumer_failures_preserve_bounded_diagnostics() -> None:
    for workflow, job, name in (
        ("assurance.yml", "postgres", "postgres-diagnostics"),
        ("assurance.yml", "research-assurance", "source-assurance-diagnostics"),
        ("ci.yml", "api-test", "api-coverage-diagnostics"),
        ("ci.yml", "repository", "repository-diagnostics"),
    ):
        step = _artifact_step(_workflow(workflow)["jobs"][job]["steps"], "upload-artifact", name)
        assert step["if"] == "always()"
        assert 1 <= step["with"]["retention-days"] <= 14
        assert all(path.startswith("var/") for path in step["with"]["path"].splitlines())


def test_repository_reads_current_measurements_in_explicit_source_context() -> None:
    steps = _workflow("ci.yml")["jobs"]["repository"]["steps"]
    command = next(step["run"] for step in steps if "make validate" in step.get("run", ""))
    for binding in (
        "MUTATION_REPORT=var/mutation-report.json",
        "REPOSITORY_CONTEXT=SOURCE_CHECKOUT",
        "PRODUCTION_CONTEXT=SOURCE_CHECKOUT",
        "CURRENT_TRUTH_CONTEXT=SOURCE_CHECKOUT",
        "PUBLISH_CURRENT_REPORTS=0",
    ):
        assert binding in command
