from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/propose_runtime_adaptation.py"


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _run(tmp_path: Path, state: object, window: object, policy: Path | None = None):
    out = tmp_path / "proposal.json"
    command = [sys.executable, str(SCRIPT), "--state", str(_write(tmp_path / "state.json", state)), "--window", str(_write(tmp_path / "window.json", window)), "--out", str(out)]
    if policy is not None:
        command.extend(["--policy", str(policy)])
    proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return proc, out


def _state() -> dict:
    return {
        "knobs": {
            "candidate_budget": 256,
            "retrieval_timeout_ms": 1200,
            "minimum_score": 0.55,
            "minimum_query_coverage": 0.60,
            "minimum_support_score": 0.65
        },
        "last_change_sequence": -1,
        "consecutive_healthy_windows": 0
    }


def _window() -> dict:
    return {
        "sequence": 10,
        "samples": 500,
        "p95_latency_ms": 500.0,
        "error_rate": 0.001,
        "contradiction_rate": 0.0,
        "overload_rate": 0.001,
        "recall_at_20": 0.95
    }


def test_cli_is_deterministic_and_emits_governed_proposal(tmp_path: Path) -> None:
    unsafe = _window() | {"error_rate": 0.05}
    first, out = _run(tmp_path, _state(), unsafe)
    assert first.returncode == 0, first.stdout
    payload = json.loads(out.read_text())
    assert payload["status"] == "PROPOSED"
    assert payload["action"] == "tighten_safety"
    assert payload["promotion"] == "GOVERNED_REVIEW_REQUIRED"
    digest = payload["proposal_sha256"]
    second, out2 = _run(tmp_path, _state(), unsafe)
    assert second.returncode == 0
    assert json.loads(out2.read_text())["proposal_sha256"] == digest


def test_cli_refuses_malformed_or_unbounded_state(tmp_path: Path) -> None:
    proc, out = _run(tmp_path, {"knobs": {"candidate_budget": 0}}, _window())
    assert proc.returncode == 2
    assert not out.exists()


def test_cli_refuses_unknown_policy_schema(tmp_path: Path) -> None:
    policy = _write(tmp_path / "policy.json", {"schema": "evil.v1"})
    proc, _ = _run(tmp_path, _state(), _window(), policy)
    assert proc.returncode == 2
    assert "unsupported plasticity policy schema" in proc.stdout
