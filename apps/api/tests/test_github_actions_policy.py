from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "validate_github_actions", ROOT / "scripts/validate_github_actions.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _workflow(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "test.yml"
    path.write_text(body, encoding="utf-8")
    return path


def test_repository_github_workflows_satisfy_policy() -> None:
    assert module.validate_repository(ROOT) == []


def test_unpinned_action_is_rejected(tmp_path: Path) -> None:
    path = _workflow(
        tmp_path,
        """name: x\non: [push]\npermissions:\n  contents: read\njobs:\n  x:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 1\n    steps:\n      - uses: actions/checkout@v7\n        with:\n          persist-credentials: false\n""",
    )
    assert any("not pinned to full SHA" in finding for finding in module.validate_workflow(path))


def test_mutable_runner_label_is_rejected(tmp_path: Path) -> None:
    path = _workflow(
        tmp_path,
        """name: x\non: [push]\npermissions:\n  contents: read\njobs:\n  x:\n    runs-on: ubuntu-latest\n    timeout-minutes: 1\n    steps: []\n""",
    )
    assert any("fixed label" in finding for finding in module.validate_workflow(path))


def test_checkout_credentials_must_not_persist(tmp_path: Path) -> None:
    path = _workflow(
        tmp_path,
        """name: x\non: [push]\npermissions:\n  contents: read\njobs:\n  x:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 1\n    steps:\n      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n""",
    )
    assert any("persist-credentials" in finding for finding in module.validate_workflow(path))


def test_privileged_pr_trigger_is_rejected(tmp_path: Path) -> None:
    path = _workflow(
        tmp_path,
        """name: x\non:\n  pull_request_target:\npermissions:\n  contents: read\njobs:\n  x:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 1\n    steps: []\n""",
    )
    assert any(
        "forbidden privileged trigger" in finding for finding in module.validate_workflow(path)
    )


def _reusable_pair(tmp_path: Path, body: str | None = None) -> Path:
    caller = tmp_path / "ci.yml"
    caller.write_text(
        "on: [push]\npermissions: {contents: read}\njobs:\n"
        "  assurance:\n    uses: ./.github/workflows/assurance.yml\n",
        encoding="utf-8",
    )
    (tmp_path / "assurance.yml").write_text(
        body
        or "on: [workflow_call]\npermissions: {contents: read}\njobs:\n"
        "  measure:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 5\n    steps: []\n",
        encoding="utf-8",
    )
    return caller


def test_local_reuse_checks_the_called_workflow(tmp_path: Path) -> None:
    assert module.validate_workflow(_reusable_pair(tmp_path)) == []
    path = tmp_path / "assurance.yml"
    path.write_text(path.read_text().replace("ubuntu-24.04", "ubuntu-latest"))
    assert any(
        "fixed label" in finding for finding in module.validate_workflow(tmp_path / "ci.yml")
    )


@pytest.mark.parametrize(
    ("change", "finding"),
    [
        ("missing", "unavailable reusable workflow"),
        ("no-call", "must declare workflow_call"),
        ("cycle", "reusable workflow cycle"),
        ("timeout", "missing positive timeout-minutes"),
        ("extra-keys", "invalid workflow call keys"),
        ("escape", "workflow call must use a local workflow file"),
    ],
)
def test_reuse_cannot_bypass_workflow_policy(tmp_path: Path, change: str, finding: str) -> None:
    caller = _reusable_pair(tmp_path)
    callee = tmp_path / "assurance.yml"
    if change == "missing":
        callee.unlink()
    elif change == "no-call":
        callee.write_text(callee.read_text().replace("workflow_call", "push"))
    elif change == "cycle":
        callee.write_text(
            "on: [workflow_call]\npermissions: {contents: read}\njobs:\n"
            "  recurse:\n    uses: ./.github/workflows/ci.yml\n"
        )
    elif change == "timeout":
        callee.write_text(callee.read_text().replace("    timeout-minutes: 5\n", ""))
    elif change == "extra-keys":
        caller.write_text(caller.read_text() + "    continue-on-error: true\n")
    elif change == "escape":
        caller.write_text(
            caller.read_text().replace("workflows/assurance", "workflows/../assurance")
        )
    assert any(finding in item for item in module.validate_workflow(caller))


def test_reusable_workflow_symlink_cannot_escape_directory(tmp_path: Path) -> None:
    folder = tmp_path / "workflows"
    folder.mkdir()
    caller = _reusable_pair(folder)
    callee = folder / "assurance.yml"
    external = tmp_path / "external.yml"
    callee.rename(external)
    callee.symlink_to(external)
    assert any("escapes" in item for item in module.validate_workflow(caller))


@pytest.mark.parametrize(
    ("jobs", "finding"),
    [
        ({"one": {"needs": "missing"}}, "unknown dependency"),
        ({"one": {"needs": "two"}, "two": {"needs": "one"}}, "job dependency cycle"),
        ({"one": {"needs": True}}, "needs must name jobs explicitly"),
    ],
)
def test_dependency_errors_are_named(jobs: dict[str, object], finding: str) -> None:
    assert any(finding in item for item in module.graph.dependency_findings("ci.yml", jobs))


def test_release_workflow_rebuilds_bound_evidence_before_packaging() -> None:
    text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    required = (
        "make validate PY=python",
        "make api-test PY=python",
        "make api-lint PY=python",
        "make eval mutation migration-gate scale operational-gate PY=python",
        "make sqlite-recovery-drill PY=python",
        "make assemble-assurance PY=python",
        "make snapshot PY=python",
        "scripts/verify_release_evidence.py",
        "scripts/package_repository.sh",
    )
    offsets = [text.find(token) for token in required]
    assert all(offset >= 0 for offset in offsets), (
        "release path is missing a required evidence step"
    )
    assert offsets == sorted(offsets), (
        "release evidence must be rebuilt and verified before packaging"
    )
