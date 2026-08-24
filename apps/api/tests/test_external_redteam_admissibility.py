from __future__ import annotations
import hashlib, json, os, subprocess, sys
from pathlib import Path
import pytest
from korpus.application.external_redteam import evaluate_external_redteam
from korpus.application.provenance import compute_source_digest
from korpus.release import RELEASE_TAG

ROOT = Path(__file__).resolve().parents[3]
PROFILE_PATH = ROOT / "config/assurance/redteam-production-v1.json"
PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
VALIDATOR = ROOT / "scripts/validate_external_redteam_evidence.py"
SIGNER = ROOT / "scripts/release_attestation.py"


def _cases() -> list[dict[str, str]]:
    return [{"id": f"case-{i}", "attack_family": family} for i, family in enumerate(PROFILE["required_attack_families"], 1)]


def _report(*, findings: list[dict[str, str]] | None = None, cases: list[dict[str, str]] | None = None, status: str = "PASS") -> dict:
    return {"status": status, "test_cases": _cases() if cases is None else cases, "findings": [] if findings is None else findings}


def test_all_required_families_and_no_blocking_findings_pass_content_recomputation() -> None:
    verdict = evaluate_external_redteam(_report(), PROFILE)
    assert verdict["pass"] is True
    assert verdict["covered_attack_families"] == sorted(PROFILE["required_attack_families"])


def test_declared_pass_cannot_hide_missing_attack_family() -> None:
    verdict = evaluate_external_redteam(_report(cases=_cases()[:-1]), PROFILE)
    assert verdict["pass"] is False
    assert verdict["checks"]["required_attack_families_covered"] is False
    assert verdict["checks"]["declared_status_consistent"] is False


@pytest.mark.parametrize("severity", ["CRITICAL", "HIGH"])
def test_open_blocking_finding_refuses_promotion(severity: str) -> None:
    finding = {"id": "F-1", "severity": severity, "status": "OPEN"}
    verdict = evaluate_external_redteam(_report(findings=[finding]), PROFILE)
    assert verdict["pass"] is False
    assert verdict["blocking_open"] == ["F-1"]


def test_blocking_finding_must_be_verified_fixed_not_merely_risk_accepted() -> None:
    accepted = {"id": "F-1", "severity": "HIGH", "status": "RISK_ACCEPTED"}
    fixed = {"id": "F-1", "severity": "HIGH", "status": "VERIFIED_FIXED"}
    assert evaluate_external_redteam(_report(findings=[accepted]), PROFILE)["pass"] is False
    assert evaluate_external_redteam(_report(findings=[fixed]), PROFILE)["pass"] is True


def _signed_gate(tmp_path: Path, report: dict, *, evidence_class: str = "EXTERNAL_INDEPENDENT", trust: bool = True) -> subprocess.CompletedProcess[bytes]:
    report.update({
        "schema": "korpus.external-redteam.v1", "evidence_class": evidence_class,
        "source_tree_sha256": compute_source_digest(ROOT), "release": RELEASE_TAG,
    })
    report.setdefault("preregistration_sha256", hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest())
    report_path, key, attestation, out = tmp_path / "external-redteam-report.json", tmp_path / "key.pem", tmp_path / "attestation.json", tmp_path / "gate.json"
    report_path.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    subprocess.run(["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(key)], check=True, capture_output=True)
    subprocess.run([sys.executable, str(SIGNER), "sign", "--manifest", str(report_path), "--key", str(key), "--out", str(attestation)], cwd=ROOT, check=True, capture_output=True)
    fingerprint = json.loads(attestation.read_text(encoding="utf-8"))["public_key_sha256"]
    env = os.environ.copy(); env.update({"GITLAB_CI":"true", "CI_COMMIT_REF_PROTECTED":"true", "PYTHONPATH":".:apps/api/src:scripts"})
    if trust:
        env["KORPUS_TRUSTED_EXTERNAL_REDTEAM_SIGNER_SHA256"] = fingerprint
    else:
        env.pop("KORPUS_TRUSTED_EXTERNAL_REDTEAM_SIGNER_SHA256", None)
    return subprocess.run([sys.executable, str(VALIDATOR), "--report", str(report_path), "--attestation", str(attestation), "--out", str(out)], cwd=ROOT, env=env, capture_output=True)


def test_trusted_signature_cannot_turn_structurally_incomplete_report_into_pass(tmp_path: Path) -> None:
    result = _signed_gate(tmp_path, _report(cases=[]))
    assert result.returncode != 0
    assert b"required_attack_families_covered" in result.stdout


def test_trusted_signature_cannot_bypass_wrong_preregistration(tmp_path: Path) -> None:
    report = _report(); report["preregistration_sha256"] = "0" * 64
    result = _signed_gate(tmp_path, report)
    assert result.returncode != 0
    assert b"preregistered" in result.stdout


def test_trusted_complete_structured_report_passes_external_gate(tmp_path: Path) -> None:
    result = _signed_gate(tmp_path, _report())
    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()


def test_valid_signature_without_preadmitted_trust_root_is_rejected(tmp_path: Path) -> None:
    result = _signed_gate(tmp_path, _report(), trust=False)
    assert result.returncode != 0
    assert b"trusted_signer" in result.stdout


def test_signed_internal_report_cannot_claim_external_independence(tmp_path: Path) -> None:
    result = _signed_gate(tmp_path, _report(), evidence_class="INTERNAL_ADVERSARIAL")
    assert result.returncode != 0
    assert b"independent_class" in result.stdout
