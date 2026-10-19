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


def test_retired_gitlab_release_job_is_inert() -> None:
    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    assert ci["workflow"]["rules"] == [{"when": "never"}]
    for name in ("production:release", "gcp:deploy-production"):
        job = ci[name]
        assert job["rules"] == [{"when": "never"}]
        commands = "\n".join(job.get("script", []))
        assert "exit 1" in commands or "false" in commands
        assert not job.get("environment")
        assert not job.get("id_tokens")
        assert not job.get("needs")
        assert not job.get("dependencies")


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
