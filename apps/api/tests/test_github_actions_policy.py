from __future__ import annotations

import importlib.util
from pathlib import Path

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
    assert any("forbidden privileged trigger" in finding for finding in module.validate_workflow(path))


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
    assert all(offset >= 0 for offset in offsets), "release path is missing a required evidence step"
    assert offsets == sorted(offsets), "release evidence must be rebuilt and verified before packaging"
