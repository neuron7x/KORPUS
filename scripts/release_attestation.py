#!/usr/bin/env python3
"""Create and verify Ed25519 detached attestations; trust is explicit governance state."""
from __future__ import annotations
import argparse, base64, hashlib, json, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]
from korpus.application.assurance_trust import trusted_fingerprints  # noqa: E402
from korpus.application.attested_evidence import verify_ed25519_attestation  # noqa: E402
from release_identity import release_tag  # noqa: E402


def sha256(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def _openssl(*args: str, input_bytes: bytes | None = None): return subprocess.run(["openssl", *args], input=input_bytes, capture_output=True, check=False)

def sign(manifest: Path, key: Path, out: Path) -> int:
    if not key.is_file(): raise SystemExit("signing key is missing")
    with tempfile.TemporaryDirectory() as td:
        signature, public = Path(td) / "signature.bin", Path(td) / "public.pem"
        signed = _openssl("pkeyutl", "-sign", "-rawin", "-inkey", str(key), "-in", str(manifest), "-out", str(signature))
        if signed.returncode != 0: raise SystemExit(signed.stderr.decode(errors="replace"))
        derived = _openssl("pkey", "-in", str(key), "-pubout", "-out", str(public))
        if derived.returncode != 0: raise SystemExit(derived.stderr.decode(errors="replace"))
        public_bytes = public.read_bytes(); payload = {
            "schema": "korpus.release-attestation.v1", "algorithm": "Ed25519", "release": release_tag(),
            "manifest": manifest.name, "manifest_sha256": sha256(manifest), "public_key_pem": public_bytes.decode("ascii"),
            "public_key_sha256": hashlib.sha256(public_bytes).hexdigest(),
            "signature_base64": base64.b64encode(signature.read_bytes()).decode("ascii"),
            "trust_class": "KEY_PROVIDED_BY_RELEASE_OPERATOR",
        }
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("release", "manifest_sha256", "public_key_sha256", "trust_class")}, indent=2)); return 0

def _trusted(path: Path | None, field: str) -> set[str]:
    if path is None or not path.is_file(): return set()
    payload = json.loads(path.read_text(encoding="utf-8")); return {str(value) for value in payload.get(field, ())}

def verify(manifest: Path, attestation_path: Path, *, trust_config: Path | None = None, trust_field: str = "release_ed25519_public_key_sha256", trust_env: str | None = None, require_trusted: bool = False) -> int:
    attestation = json.loads(attestation_path.read_text(encoding="utf-8")); trusted = trusted_fingerprints(trust_config or Path("/nonexistent"), trust_field, trust_env) if trust_env else _trusted(trust_config, trust_field)
    verdict = verify_ed25519_attestation(manifest.read_bytes(), manifest_name=manifest.name, release=release_tag(), attestation=attestation, trusted_fingerprints=trusted)
    checks = dict(verdict.checks)
    if not require_trusted: checks.pop("trusted_signer", None)
    failures = [name for name, ok in checks.items() if not ok]
    print(json.dumps({"valid": not failures, "checks": checks, "failures": failures, "public_key_sha256": verdict.fingerprint}, indent=2)); return int(bool(failures))

def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    signer = sub.add_parser("sign"); signer.add_argument("--manifest", type=Path, required=True); signer.add_argument("--key", type=Path, required=True); signer.add_argument("--out", type=Path, required=True)
    verifier = sub.add_parser("verify"); verifier.add_argument("--manifest", type=Path, required=True); verifier.add_argument("--attestation", type=Path, required=True); verifier.add_argument("--trust-config", type=Path); verifier.add_argument("--trust-field", default="release_ed25519_public_key_sha256"); verifier.add_argument("--trust-env"); verifier.add_argument("--require-trusted", action="store_true")
    args = parser.parse_args()
    return sign(args.manifest, args.key, args.out) if args.command == "sign" else verify(args.manifest, args.attestation, trust_config=args.trust_config, trust_field=args.trust_field, trust_env=args.trust_env, require_trusted=args.require_trusted)
if __name__ == "__main__": raise SystemExit(main())
