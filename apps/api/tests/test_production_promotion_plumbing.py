from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_production_assurance_verifier_accepts_runtime_trust_only_through_shared_guard() -> None:
    source = (ROOT / "scripts/verify_production_assurance.py").read_text(encoding="utf-8")
    assert "KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256" in source
    assert "trusted_fingerprints(" in source


def test_release_attestation_can_use_protected_runtime_trust(tmp_path: Path) -> None:
    script = ROOT / "scripts/release_attestation.py"
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
    manifest.write_text('{"kind":"promotion-test"}\n', encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(script),
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
    fingerprint = json.loads(attestation.read_text(encoding="utf-8"))["public_key_sha256"]
    empty = tmp_path / "empty.json"
    empty.write_text('{"release_ed25519_public_key_sha256":[]}\n', encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "GITLAB_CI": "true",
            "CI_COMMIT_REF_PROTECTED": "true",
            "KORPUS_RELEASE_TRUST": fingerprint,
            "PYTHONPATH": ".:apps/api/src:scripts",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "verify",
            "--manifest",
            str(manifest),
            "--attestation",
            str(attestation),
            "--trust-config",
            str(empty),
            "--trust-env",
            "KORPUS_RELEASE_TRUST",
            "--require-trusted",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()


def test_production_release_job_is_protected_tag_only_and_requires_external_roots() -> None:
    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    job = ci["production:release"]
    rules = json.dumps(job["rules"])
    assert "CI_COMMIT_TAG" in rules and "CI_COMMIT_REF_PROTECTED" in rules
    script = "\n".join(job["script"])
    for name in (
        "KORPUS_PRODUCTION_ASSURANCE_SIGNING_KEY_FILE",
        "KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256",
        "KORPUS_RELEASE_SIGNING_KEY_FILE",
        "KORPUS_TRUSTED_RELEASE_SIGNER_SHA256",
    ):
        assert name in script
    assert (
        'test "$KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256" != "$KORPUS_TRUSTED_RELEASE_SIGNER_SHA256"'
        in script
    )
    assert (
        script.index(
            "release_attestation.py sign --manifest reports/PRODUCTION_ASSURANCE_REPORT.json"
        )
        < script.index("verify_production_assurance.py")
        < script.index("package_production_release.sh")
    )


def test_production_release_script_requires_runtime_release_trust() -> None:
    source = (ROOT / "scripts/package_production_release.sh").read_text(encoding="utf-8")
    assert "--trust-env KORPUS_TRUSTED_RELEASE_SIGNER_SHA256 --require-trusted" in source
    assert (
        '[[ "$KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256" != "$KORPUS_TRUSTED_RELEASE_SIGNER_SHA256" ]]'
        in source
    )
    assert '[[ "$GITLAB_CI" == "true" ]]' in source
    assert '[[ "$CI_COMMIT_REF_PROTECTED" == "true" ]]' in source
    assert '[[ "$CI_COMMIT_TAG" == "$expected_tag" ]]' in source
