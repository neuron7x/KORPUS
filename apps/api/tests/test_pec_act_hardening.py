from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from korpus.application.pec_training import TrainingRow, grouped_folds
from korpus.pec_config_policy import validate_pec_settings


def test_controlled_contextual_retrieval_cannot_run_outside_pec_governance() -> None:
    settings = SimpleNamespace(
        pec_enabled=False,
        pec_profile_sha256=None,
        pec_profile_path=None,
        contextual_retrieval_enabled=True,
    )
    with pytest.raises(ValueError, match="controlled contextual retrieval requires PEC governance"):
        validate_pec_settings(settings, controlled=True)


def test_grouped_folds_never_split_a_group_across_train_and_validation() -> None:
    rows = [
        TrainingRow(f"q-{group}-{index}", group, {"candidate_count": index}, "ABSTAIN")
        for group in ("документ-А", "документ-Б", "document-C", "document-D")
        for index in range(3)
    ]
    folds = grouped_folds(rows, folds=3)
    for train, valid in folds:
        train_groups = {row.group_id for row in train}
        valid_groups = {row.group_id for row in valid}
        assert train_groups.isdisjoint(valid_groups)


def test_dataset_audit_rejects_group_partition_leakage(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    rows = [
        {
            "id": "q1",
            "query": "alpha",
            "group_id": "same",
            "partition": "train",
            "gold_version_ids": [],
        },
        {
            "id": "q2",
            "query": "beta",
            "group_id": "same",
            "partition": "locked_eval",
            "gold_version_ids": [],
        },
    ]
    dataset.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    import subprocess
    import sys

    root = Path(__file__).resolve().parents[3]
    receipt_path = tmp_path / "audit.json"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/audit_pec_eval_dataset.py",
            "--dataset",
            str(dataset),
            "--out",
            str(receipt_path),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    report = json.loads(receipt_path.read_text())
    assert report["status"] == "FAIL"
    assert any(issue.startswith("group_partition_leakage:same:") for issue in report["issues"])


def test_replay_rejects_string_booleans_in_observed_outcomes(tmp_path: Path) -> None:
    import hashlib
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[3]
    dataset = tmp_path / "dataset.jsonl"
    observations = tmp_path / "observations.jsonl"
    report_path = tmp_path / "replay.json"
    dataset.write_text(
        json.dumps({"id": "q1", "query": "alpha", "group_id": "g1", "partition": "train"}) + "\n",
        encoding="utf-8",
    )
    observation = {
        "query_id": "q1",
        "group_id": "g1",
        "action": "STOP_USE_CURRENT_EVIDENCE",
        "state_fingerprint": hashlib.sha256(b"state").hexdigest(),
        "features": {},
        "authorization_ok": "false",
        "answer_error": False,
        "quality_ok": True,
        "answer_status": "insufficient_evidence",
        "gold_hit": False,
        "latency_ms": 1.0,
        "search_count": 1,
        "planner_calls": 0,
        "semantic_calls": 0,
        "candidate_count": 1,
    }
    observations.write_text(json.dumps(observation) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/run_counterfactual_replay.py",
            "--dataset",
            str(dataset),
            "--observations",
            str(observations),
            "--actions",
            "STOP_USE_CURRENT_EVIDENCE",
            "--out",
            str(report_path),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    report = json.loads(report_path.read_text())
    assert report["status"] == "FAIL"
    assert any(
        "invalid_boolean:q1:STOP_USE_CURRENT_EVIDENCE:authorization_ok" in issue
        for issue in report["validation_issues"]
    )
