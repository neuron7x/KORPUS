from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_dataset_builder_accepts_repository_relative_paths() -> None:
    var = ROOT / "var"
    var.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pec-dataset-", dir=var) as raw:
        target = Path(raw)
        out = target / "pec_eval.jsonl"
        receipt = target / "receipt.json"
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/build_pec_eval_dataset.py",
                "--source",
                "evals/datasets/reference.jsonl",
                "--out",
                str(out.relative_to(ROOT)),
                "--receipt",
                str(receipt.relative_to(ROOT)),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert out.exists()
        assert receipt.exists()


def test_controller_verifier_fails_on_promoted_oracle_mismatch() -> None:
    import hashlib
    import json

    from korpus.application.controller_profile import (
        ControllerLeaf,
        ControllerProfile,
        ControllerRule,
    )
    from korpus.application.evidence_state import EvidenceState, feature_schema_sha256

    var = ROOT / "var"
    var.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pec-verify-", dir=var) as raw:
        target = Path(raw)
        dataset = target / "dataset.jsonl"
        manifest = target / "manifest.json"
        protocol = target / "protocol.md"
        replay = target / "replay.json"
        training = target / "training.json"
        oracle = target / "oracle.json"
        profile_path = target / "profile.json"
        report_path = target / "verify.json"
        for path, payload in (
            (dataset, '{"id":"q1"}\n'),
            (manifest, '{"system":"test"}\n'),
            (protocol, "# test protocol\n"),
            (replay, '{"status":"PASS"}\n'),
            (training, '{"status":"PASS"}\n'),
        ):
            path.write_text(payload, encoding="utf-8")

        def digest(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        state = EvidenceState(
            schema_version=2,
            query_risk="standard",
            query_token_count=2,
            candidate_count=1,
            top1_score=0.9,
            top1_top2_margin=0.9,
            top1_query_coverage=0.9,
            mean_topk_query_coverage=0.9,
            score_concentration=1.0,
            highest_authority_class="official_primary",
            top_authority_count=1,
            evidence_redundancy=0.0,
            original_query_has_eligible_evidence=True,
            eligible_evidence_count=1,
            structural_candidate_exists=True,
            retrieval_gate_passed=True,
            best_score_margin=0.4,
            best_query_coverage_margin=0.4,
            best_authority_margin=0.0,
            minimum_admission_margin=0.4,
            decision_boundary_distance=0.4,
            planner_already_used=False,
            semantic_available=False,
            sparse_dense_overlap=0.0,
            rank_disagreement=0.0,
            inference_cycles_used=1,
            inference_evidence_items=1,
            inference_conflicts=0,
        )
        features = state.canonical_dict()
        features.pop("schema_version")
        oracle.write_text(
            json.dumps(
                {
                    "decisions": [
                        {
                            "query_id": "q1",
                            "oracle_status": "PASS",
                            "oracle_action": "PLAN_QUERY_VARIANTS",
                            "features": features,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        profile = ControllerProfile(
            profile_id="pec-verifier-test",
            dataset_sha256=digest(dataset),
            system_manifest_sha256=digest(manifest),
            evaluation_protocol_sha256=digest(protocol),
            replay_receipt_sha256=digest(replay),
            training_receipt_sha256=digest(training),
            feature_schema_sha256=feature_schema_sha256(),
            corpus_release_id="a" * 16,
            answer_calibration_id="cal-test",
            admission_status="PASS",
            controller_risk_limit=0.05,
            minimum_leaf_samples=1,
            rules=(
                ControllerRule(
                    rule_id="always-stop",
                    leaf=ControllerLeaf(
                        leaf_id="stop",
                        action="STOP_USE_CURRENT_EVIDENCE",
                        admitted=True,
                        observed_samples=10,
                        upper_error_bound=0.0,
                    ),
                ),
            ),
        )
        profile_path.write_text(profile.canonical_json() + "\n", encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                "scripts/verify_pec_controller.py",
                "--profile",
                str(profile_path),
                "--dataset",
                str(dataset),
                "--system-manifest",
                str(manifest),
                "--evaluation-protocol",
                str(protocol),
                "--replay-receipt",
                str(replay),
                "--training-receipt",
                str(training),
                "--oracle",
                str(oracle),
                "--release-gate",
                "--out",
                str(report_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        report = json.loads(report_path.read_text())
        assert report["status"] == "FAIL"
        assert report["mismatch_count"] == 1
        assert "promoted_controller_oracle_mismatch" in report["errors"]


def test_controller_export_refuses_cross_run_training_binding() -> None:
    import hashlib
    import json

    var = ROOT / "var"
    var.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pec-export-", dir=var) as raw:
        target = Path(raw)
        dataset = target / "dataset.jsonl"
        manifest = target / "manifest.json"
        protocol = target / "protocol.md"
        replay = target / "replay.json"
        oracle = target / "oracle.json"
        training = target / "training.json"
        profile = target / "profile.json"
        report = target / "export.json"
        dataset.write_text('{"id":"q1"}\n', encoding="utf-8")
        manifest.write_text('{"system":"test"}\n', encoding="utf-8")
        protocol.write_text("# protocol\n", encoding="utf-8")

        def digest(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        replay.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "dataset_sha256": digest(dataset),
                    "corpus_release_id": "a" * 16,
                    "evaluation_protocol_sha256": digest(protocol),
                    "answer_calibration_id": "cal-test",
                }
            ),
            encoding="utf-8",
        )
        oracle.write_text(
            json.dumps({"status": "PASS", "replay_sha256": digest(replay), "decisions": []}),
            encoding="utf-8",
        )
        training.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "dataset_sha256": "f" * 64,
                    "oracle_sha256": digest(oracle),
                    "controller_risk_limit": 0.05,
                    "minimum_leaf_samples": 1,
                    "leaves": [],
                }
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/export_pec_controller.py",
                "--training",
                str(training),
                "--oracle",
                str(oracle),
                "--dataset",
                str(dataset),
                "--system-manifest",
                str(manifest),
                "--evaluation-protocol",
                str(protocol),
                "--replay-receipt",
                str(replay),
                "--corpus-release-id",
                "a" * 16,
                "--answer-calibration-id",
                "cal-test",
                "--profile-id",
                "pec-export-test",
                "--out",
                str(profile),
                "--receipt",
                str(report),
                "--release-gate",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        payload = json.loads(report.read_text())
        assert payload["status"] == "FAIL"
        assert "binding_mismatch:training.dataset_sha256" in payload["errors"]
