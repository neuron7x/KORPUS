from __future__ import annotations
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]
CI = ROOT / ".gitlab-ci.yml"


def _jobs() -> dict[str, dict]:
    document = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return {name: body for name, body in document.items() if isinstance(body, dict)}


def _script(job: dict) -> str:
    return "\n".join(str(line) for line in job.get("script", ()))


def test_postgres_job_materializes_network_load_evidence_as_fixture() -> None:
    job = _jobs()["api:postgres-and-restore"]
    script = _script(job)
    assert "python -m uvicorn korpus.main:app" in script
    assert "scripts/load_probe.py" in script
    assert "--environment-class CI_FIXTURE" in script
    assert "var/load-probe.json" in (job.get("artifacts") or {}).get("paths", ())


def test_package_consumes_postgres_artifacts_and_stages_external_evidence_before_gate() -> None:
    job = _jobs()["source:package"]
    needs = {item["job"]: item for item in job.get("needs", ()) if isinstance(item, dict)}
    assert needs["api:postgres-and-restore"].get("artifacts") is True
    script = _script(job)
    stage_at = script.index("stage_external_production_evidence.py")
    gate_at = script.index("run_reliability_gate.py")
    assert stage_at < gate_at


def test_supply_chain_attestation_is_optional_but_gate_remains_mandatory() -> None:
    script = _script(_jobs()["source:package"])
    assert "KORPUS_SUPPLY_CHAIN_SIGNING_KEY_FILE" in script
    assert "release_attestation.py sign" in script
    assert "run_supply_chain_gate.py" in script


def test_evidence_registry_tracks_the_canonical_load_report_name() -> None:
    from scripts.evidence_registry import KEPT
    assert "load-probe.json" in KEPT
    assert "load-probe-api.json" not in KEPT


def test_package_materializes_all_externally_bound_required_gates() -> None:
    script = _script(_jobs()["source:package"])
    assert "run_tevv_production_gate.py" in script
    assert "validate_external_redteam_evidence.py" in script
    assert "run_reliability_gate.py" in script


def test_redteam_validator_uses_protected_runtime_trust_without_source_mutation() -> None:
    source = (ROOT / "scripts/validate_external_redteam_evidence.py").read_text(encoding="utf-8")
    assert 'trusted_fingerprints(TRUST, "ed25519_public_key_sha256", "KORPUS_TRUSTED_EXTERNAL_REDTEAM_SIGNER_SHA256")' in source


def test_container_scan_marker_is_handed_to_supply_chain_gate() -> None:
    jobs = _jobs(); scan = jobs["container:scan"]; package = jobs["source:package"]
    assert "var/security/ci-container-scan.json" in (scan.get("artifacts") or {}).get("paths", ())
    needs = {item["job"]: item for item in package.get("needs", ()) if isinstance(item, dict)}
    assert needs["container:scan"].get("artifacts") is True
    manifest_builder = (ROOT / "scripts/build_supply_chain_evidence_manifest.py").read_text(encoding="utf-8")
    gate = (ROOT / "scripts/run_supply_chain_gate.py").read_text(encoding="utf-8")
    assert '"var/security/ci-container-scan.json"' in manifest_builder
    assert 'container_scan=_json(paths[names[4]])' in gate
