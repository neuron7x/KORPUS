"""The operational gate must reject evidence that did not come from this tree.

Destruction stage 2026-08-03: the gate returned PASS for artifacts stamped
``source_commit='0'*40`` — evidence from a tree that does not exist. These tests
reproduce that attack against the current gate and require it to go red.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from korpus.application.operations import OperationalReleaseGate
from korpus.application.provenance import (
    PROVENANCE_KEY,
    ProvenanceError,
    compute_source_digest,
    read_provenance,
    stamp,
    verify_reports,
)

from apps.api.tests.test_operations import passing_reports

POLICY = Path("config/operations/reference-v5.json")
ROOT = Path(__file__).resolve().parents[3]
FOREIGN_DIGEST = "0" * 64


def stamped_reports(digest: str) -> dict:
    reports = passing_reports()
    for report in reports.values():
        report[PROVENANCE_KEY] = {
            "schema_version": 1,
            "source_digest": digest,
            "generator": "test",
            "generated_at": "2026-08-04T00:00:00+00:00",
        }
    return reports


def test_gate_passes_only_when_every_report_carries_this_tree() -> None:
    result = OperationalReleaseGate.load(POLICY).evaluate(
        stamped_reports("a" * 64), source_digest="a" * 64
    )
    assert result.passed is True
    assert result.checks["evidence_provenance"] is True


def test_gate_rejects_evidence_from_a_foreign_tree() -> None:
    result = OperationalReleaseGate.load(POLICY).evaluate(
        stamped_reports(FOREIGN_DIGEST), source_digest="a" * 64
    )
    assert result.passed is False
    assert result.checks["evidence_provenance"] is False
    assert any("different source tree" in failure for failure in result.failures)


def test_gate_rejects_a_single_stale_report_among_fresh_ones() -> None:
    reports = stamped_reports("a" * 64)
    reports["mutation"][PROVENANCE_KEY]["source_digest"] = "b" * 64
    result = OperationalReleaseGate.load(POLICY).evaluate(reports, source_digest="a" * 64)
    assert result.passed is False
    assert any(failure.startswith("mutation:") for failure in result.failures)


def test_gate_rejects_reports_without_provenance() -> None:
    result = OperationalReleaseGate.load(POLICY).evaluate(passing_reports(), source_digest="a" * 64)
    assert result.passed is False
    assert any("no provenance" in failure for failure in result.failures)


def test_gate_without_a_digest_cannot_pass() -> None:
    result = OperationalReleaseGate.load(POLICY).evaluate(stamped_reports("a" * 64))
    assert result.passed is False
    assert result.checks["evidence_provenance"] is False


@pytest.mark.parametrize(
    "block",
    [
        None,
        "not-a-mapping",
        {"schema_version": 2, "source_digest": "a" * 64, "generator": "g", "generated_at": "t"},
        {"schema_version": 1, "source_digest": "short", "generator": "g", "generated_at": "t"},
        {"schema_version": 1, "source_digest": "a" * 64, "generator": "", "generated_at": "t"},
        {"schema_version": 1, "source_digest": "a" * 64, "generator": "g", "generated_at": ""},
    ],
)
def test_malformed_provenance_is_not_provenance(block: object) -> None:
    with pytest.raises(ProvenanceError):
        read_provenance({PROVENANCE_KEY: block} if block is not None else {})


def test_verify_reports_rejects_a_malformed_expected_digest() -> None:
    ok, reasons = verify_reports(stamped_reports("a" * 64), "not-a-digest")
    assert ok is False
    assert reasons


def test_digest_changes_when_evidence_bearing_source_changes(tmp_path: Path) -> None:
    tree = tmp_path / "repo"
    (tree / "apps/api/src/korpus").mkdir(parents=True)
    (tree / "docs").mkdir(parents=True)
    module = tree / "apps/api/src/korpus/policy.py"
    module.write_text("threshold = 1.0\n", encoding="utf-8")
    (tree / "docs/README.md").write_text("first\n", encoding="utf-8")

    baseline = compute_source_digest(tree)
    module.write_text("threshold = 0.0\n", encoding="utf-8")
    assert compute_source_digest(tree) != baseline


def test_digest_ignores_documentation_so_the_gate_stays_signal(tmp_path: Path) -> None:
    tree = tmp_path / "repo"
    (tree / "apps/api/src").mkdir(parents=True)
    (tree / "docs").mkdir(parents=True)
    (tree / "apps/api/src/policy.py").write_text("threshold = 1.0\n", encoding="utf-8")
    doc = tree / "docs/README.md"
    doc.write_text("first\n", encoding="utf-8")

    baseline = compute_source_digest(tree)
    doc.write_text("second, entirely rewritten\n", encoding="utf-8")
    assert compute_source_digest(tree) == baseline


def test_digest_ignores_generated_bytecode_and_caches(tmp_path: Path) -> None:
    tree = tmp_path / "repo"
    package = tree / "apps/api/src/korpus/__pycache__"
    package.mkdir(parents=True)
    (tree / "apps/api/src/korpus/policy.py").write_text("x = 1\n", encoding="utf-8")
    baseline = compute_source_digest(tree)
    (package / "policy.cpython-312.pyc").write_bytes(b"\x00\x01")
    assert compute_source_digest(tree) == baseline


def test_digest_separates_path_from_content(tmp_path: Path) -> None:
    """Moving a byte from the file name into the file body must not collide.

    Without length framing both trees hash the concatenation "scripts/abc",
    so a foreign tree could be renamed into a matching digest.
    """

    left = tmp_path / "left"
    right = tmp_path / "right"
    (left / "scripts").mkdir(parents=True)
    (right / "scripts").mkdir(parents=True)
    (left / "scripts/ab").write_text("c", encoding="utf-8")
    (right / "scripts/a").write_text("bc", encoding="utf-8")
    assert compute_source_digest(left) != compute_source_digest(right)


def test_stamp_requires_a_generator(tmp_path: Path) -> None:
    with pytest.raises(ProvenanceError):
        stamp(tmp_path, "")


def test_stamp_binds_to_the_tree_it_is_given(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/run.py").write_text("pass\n", encoding="utf-8")
    block = stamp(tmp_path, "scripts/run.py")
    assert block["source_digest"] == compute_source_digest(tmp_path)
    assert read_provenance({PROVENANCE_KEY: block}).generator == "scripts/run.py"


def test_gate_script_exits_nonzero_on_foreign_evidence(tmp_path: Path) -> None:
    """End-to-end: the executable gate, not just the class, must go red.

    The class can be called correctly by a test and incorrectly by the script.
    This runs the real entry point against artifacts from a foreign tree.
    """

    var = ROOT / "var"
    sources = {
        "eval": var / "eval-report.json",
        "mutation": var / "mutation-report.json",
        "migration": var / "migration-report.json",
        "scale": var / "scale-report.json",
    }
    missing = [name for name, path in sources.items() if not path.is_file()]
    if missing:
        pytest.skip(f"assurance artifacts absent: {missing}")

    backup = {name: path.read_bytes() for name, path in sources.items()}
    try:
        for path in sources.values():
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload[PROVENANCE_KEY] = {
                "schema_version": 1,
                "source_digest": FOREIGN_DIGEST,
                "generator": "forged",
                "generated_at": "2026-08-04T00:00:00+00:00",
            }
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "scripts/run_operational_gate.py"],
            cwd=ROOT,
            env={"PYTHONPATH": str(ROOT / "apps/api/src"), "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode != 0, completed.stdout
        assert "evidence_provenance" in completed.stdout
    finally:
        for name, path in sources.items():
            path.write_bytes(backup[name])
