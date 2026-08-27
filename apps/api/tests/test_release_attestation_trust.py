from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/release_attestation.py"


def test_release_attestation_requires_pretrusted_signer(tmp_path: Path) -> None:
    key, manifest, attestation = (
        tmp_path / "key.pem",
        tmp_path / "manifest.json",
        tmp_path / "attestation.json",
    )
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(key)],
        check=True,
        capture_output=True,
    )
    manifest.write_text('{"release":"test"}\n', encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "sign",
            "--manifest",
            str(manifest),
            "--key",
            str(key),
            "--out",
            str(attestation),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    empty = tmp_path / "empty.json"
    empty.write_text('{"release_ed25519_public_key_sha256":[]}\n', encoding="utf-8")
    rejected = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "verify",
            "--manifest",
            str(manifest),
            "--attestation",
            str(attestation),
            "--trust-config",
            str(empty),
            "--require-trusted",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode != 0
    fingerprint = json.loads(attestation.read_text())["public_key_sha256"]
    trusted = tmp_path / "trusted.json"
    trusted.write_text(json.dumps({"release_ed25519_public_key_sha256": [fingerprint]}) + "\n")
    accepted = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "verify",
            "--manifest",
            str(manifest),
            "--attestation",
            str(attestation),
            "--trust-config",
            str(trusted),
            "--require-trusted",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stdout.decode() + accepted.stderr.decode()
