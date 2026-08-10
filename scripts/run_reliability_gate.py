#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src")); sys.path.insert(0, str(ROOT / "scripts"))
from korpus.application.assurance_evidence import evaluate_attested_reliability  # noqa: E402
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402
TRUST = ROOT / "config/assurance/trusted-assurance-signers.json"
def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
def _bytes(path: Path) -> bytes:
    return path.read_bytes() if path.is_file() else b""

def main() -> int:
    load_path, recovery_path = ROOT / "var/load-probe.json", ROOT / "var/recovery-report.json"
    internal = _read(ROOT / "var/production/reliability_internal-gate.json")
    chaos, load, recovery = _read(ROOT / "var/chaos-matrix.json"), _read(load_path), _read(recovery_path)
    source, release = compute_source_digest(ROOT), release_tag()
    trusted = set(_read(TRUST).get("environment_ed25519_public_key_sha256", ()))
    checks, load_fp, recovery_fp = evaluate_attested_reliability(
        internal, chaos, load, recovery, source=source, release=release,
        load_bytes=_bytes(load_path),
        recovery_bytes=_bytes(recovery_path),
        load_attestation=_read(ROOT / "var/production/load-probe.attestation.json"),
        recovery_attestation=_read(ROOT / "var/production/recovery-report.attestation.json"), trusted=trusted,
    )
    failures = [name for name, ok in checks.items() if not ok]
    status = {False: "PASS", True: "FAIL"}[bool(failures)]
    result = gate_payload("reliability", status=status, source_digest=source,
        release=release, checks=checks, failures=failures, evidence_class="ATTESTED_LIVE_PLUS_FAULT_INJECTION_REQUIRED",
        load_metrics={name: load.get(name, {}) for name in ("load", "spike", "soak")}, chaos_cases=len(chaos.get("cases", ())),
        recovery_status=recovery.get("status", "NOT_EXECUTED"), load_signer_fingerprint=load_fp, recovery_signer_fingerprint=recovery_fp)
    out = ROOT / "var/production/reliability-gate.json"; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(failures))

if __name__ == "__main__":
    raise SystemExit(main())
