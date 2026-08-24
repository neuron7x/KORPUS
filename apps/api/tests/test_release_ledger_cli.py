from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from korpus.application.release_ledger import ReleaseLedgerEvent

ROOT = Path(__file__).resolve().parents[3]


def _event() -> ReleaseLedgerEvent:
    return ReleaseLedgerEvent(
        sequence=1,
        release_identity_digest="a" * 64,
        release="v9.9.9",
        from_stage="DRAFT",
        to_stage="INTEGRATED",
        author_subject="author",
        verifier_subject=None,
        gate_set_sha256="b" * 64,
        timestamp="2026-08-15T12:00:00Z",
        previous_event_sha256="0" * 64,
    ).with_hash()


def test_cli_verifies_round_tripped_jsonl_and_external_head(tmp_path: Path) -> None:
    event = _event()
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(event.as_dict(), sort_keys=True) + "\n", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/release_ledger_cli.py",
            "verify",
            "--ledger",
            str(ledger),
            "--expected-release-identity-digest",
            "a" * 64,
            "--expected-head-sha256",
            event.event_sha256,
        ],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "apps/api/src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["status"] == "PASS"


def test_cli_refuses_suffix_anchor_mismatch(tmp_path: Path) -> None:
    event = _event()
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(event.as_dict()) + "\n", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/release_ledger_cli.py",
            "verify",
            "--ledger",
            str(ledger),
            "--expected-head-sha256",
            "f" * 64,
        ],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "apps/api/src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["status"] == "FAIL"
    assert "ledger.head_anchor_mismatch" in payload["failures"]
