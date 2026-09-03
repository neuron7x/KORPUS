from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from run_handoff_liveness_probe import synthetic_binding  # noqa: E402

DIGEST = "a" * 64
CURRENT = "b" * 64


def test_a_valid_stale_binding_is_rebound_only_in_memory() -> None:
    report = {
        "status": "PASS",
        "tracked_tree_scope": "tracked_tree",
        "tracked_tree_sha256": DIGEST,
    }

    rebound = synthetic_binding(report, CURRENT)

    assert rebound["tracked_tree_sha256"] == CURRENT
    assert report["tracked_tree_sha256"] == DIGEST


@pytest.mark.parametrize(
    "report",
    [
        {
            "status": "PASS",
            "tracked_tree_scope": "tracked_tree",
            "tracked_tree_sha256": "0" + DIGEST,
        },
        {
            "status": "PASS",
            "tracked_tree_scope": "evidence_paths",
            "tracked_tree_sha256": DIGEST,
        },
        {"status": "PASS", "tracked_tree_scope": "tracked_tree"},
        {
            "status": "FAIL",
            "tracked_tree_scope": "tracked_tree",
            "tracked_tree_sha256": DIGEST,
        },
    ],
)
def test_a_poisoned_or_failed_report_is_never_rebound(report: dict[str, object]) -> None:
    assert synthetic_binding(report, CURRENT) == report
