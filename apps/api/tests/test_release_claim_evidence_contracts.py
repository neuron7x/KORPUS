from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from korpus.application.github_assurance_receipts import (
    CANONICAL_OWNER_ID,
    CANONICAL_REPOSITORY,
    CANONICAL_REPOSITORY_ID,
    CANONICAL_WORKFLOW_ID,
    CANONICAL_WORKFLOW_PATH,
    admission_payload,
    new_receipt,
    sha256_bytes,
)
from korpus.application.release_claim_hosted import (
    ARTIFACT_GROUP,
    CLAIM_EXECUTORS,
    hosted_paths,
    new_attestation,
)
from korpus.application.release_claim_sigstore import verifier_executable
from korpus.application.release_claims import claim_status

DIGEST = "a" * 64
RELEASE = "v9"
SCOPE = "evidence_paths"


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status(root: Path, claim: str, evidence: str) -> str:
    return claim_status(root, claim, evidence, DIGEST, RELEASE)


def _commit(root: Path) -> str:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Claim Test"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "claim-test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "config", "commit.gpgsign", "false"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "--no-gpg-sign", "-m", "fixture"], check=True
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _hosted(
    root: Path,
    claim_id: str,
    artifacts: list[str],
    result: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch | None,
) -> None:
    trusted_root = root / "config/assurance/github-attestation-trusted-root.jsonl"
    trusted_root.parent.mkdir(parents=True, exist_ok=True)
    trusted_root.write_text("test root\n", encoding="utf-8")
    verifier_config = (
        Path(__file__).resolve().parents[3] / "config/assurance/sigstore-verifier.json"
    )
    (root / "config/assurance/sigstore-verifier.json").write_bytes(verifier_config.read_bytes())
    commit = _commit(root)
    dummy = root / "reports/release/hosted-test-subject.txt"
    dummy.parent.mkdir(parents=True, exist_ok=True)
    dummy.write_text("hosted\n", encoding="utf-8")
    executions = {
        candidate: {
            "executor": executor,
            "exit_code": 0,
            "result": result if candidate == claim_id else {},
            "artifacts": artifacts
            if candidate == claim_id
            else [dummy.relative_to(root).as_posix()],
        }
        for candidate, executor in CLAIM_EXECUTORS.items()
    }
    attestation = new_attestation(root, RELEASE, DIGEST, executions)
    attestation_path, receipt_path, admission_path, bundle_path = hosted_paths(RELEASE)
    _write(root / attestation_path, attestation)
    attestation_bytes = (root / attestation_path).read_bytes()
    identity = {
        "repository": CANONICAL_REPOSITORY,
        "repository_id": CANONICAL_REPOSITORY_ID,
        "repository_owner_id": CANONICAL_OWNER_ID,
        "workflow_id": CANONICAL_WORKFLOW_ID,
        "workflow_path": CANONICAL_WORKFLOW_PATH,
        "run_id": 42,
        "run_attempt": 1,
        "commit_sha": commit,
    }
    receipt = new_receipt(
        identity,
        kind="release-claims",
        job="release-claims",
        source_tree_sha256=attestation["tracked_tree_sha256"],
        artifacts={Path(attestation_path).name: attestation_bytes},
        subjects={
            "release-claims": {
                "release": RELEASE,
                "source_tree_sha256": DIGEST,
                "digest_scope": SCOPE,
                "tracked_tree_sha256": attestation["tracked_tree_sha256"],
                "source_ref": "refs/heads/main",
                "claims": sorted(CLAIM_EXECUTORS),
            }
        },
    )
    _write(root / receipt_path, receipt)
    (root / bundle_path).write_text('{"test":"not-a-real-sigstore-bundle"}\n', encoding="utf-8")
    files = {
        Path(attestation_path).name: (root / attestation_path).read_bytes(),
        Path(receipt_path).name: (root / receipt_path).read_bytes(),
        Path(bundle_path).name: (root / bundle_path).read_bytes(),
    }
    admission = admission_payload(
        identity,
        {
            ARTIFACT_GROUP: {
                "artifact_id": 99,
                "files": {
                    name: {"sha256": sha256_bytes(payload), "bytes": len(payload)}
                    for name, payload in files.items()
                },
            }
        },
    )
    _write(root / admission_path, admission)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    if monkeypatch is not None:
        monkeypatch.setattr(
            "korpus.application.release_claim_hosted_contract.sigstore_verified",
            lambda *_args, **_kwargs: True,
        )


def _web_inputs(root: Path) -> None:
    package = {
        "scripts": {
            "lint": 'node -e "process.exit(0)"',
            "test": "node --test test/*.test.mjs",
            "build": 'node -e "process.exit(0)"',
        }
    }
    _write(root / "apps/web/package.json", package)
    test = root / "apps/web/test/basic.test.mjs"
    test.parent.mkdir(parents=True)
    test.write_text(
        'import test from "node:test";\nimport assert from "node:assert/strict";\n'
        'test("one", () => assert.equal(1, 1));\n'
        'test("two", () => assert.equal(2, 2));\n',
        encoding="utf-8",
    )
    script = root / "scripts/publish_web_regression.py"
    script.parent.mkdir(parents=True)
    script.write_text("# canonical producer\n", encoding="utf-8")
    tap = root / f"reports/release/{RELEASE}/WEB_REGRESSION_REPORT.tap"
    tap.parent.mkdir(parents=True, exist_ok=True)
    tap.write_text("# tests 2\n# pass 2\n# fail 0\n# skipped 0\n", encoding="utf-8")


def _web(root: Path) -> dict[str, Any]:
    return {
        "schema": "korpus.web-regression.v1",
        "release": RELEASE,
        "status": "PASS",
        "steps": {
            "lint": {"exit_code": 0, "status": "PASS"},
            "test": {
                "exit_code": 0,
                "status": "PASS",
                "tests": 2,
                "pass": 2,
                "fail": 0,
                "skipped": 0,
            },
            "build": {"exit_code": 0, "status": "PASS"},
        },
        "tests": 2,
        "passed": 2,
        "failed": 0,
        "skipped": 0,
        "test_output_sha256": _sha(root / f"reports/release/{RELEASE}/WEB_REGRESSION_REPORT.tap"),
        "evidence_class": "LOCAL_NODE_TEST_RUNNER",
        "provenance": {
            "schema_version": 1,
            "source_digest": DIGEST,
            "digest_scope": SCOPE,
            "generator": "scripts/publish_web_regression.py",
            "generated_at": "2026-10-19T00:00:00+00:00",
        },
    }


def test_web_claim_requires_exact_hosted_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = f"reports/release/{RELEASE}/WEB_REGRESSION_REPORT.json"
    _web_inputs(tmp_path)
    _write(tmp_path / evidence, _web(tmp_path))
    result = {"tests": 2, "pass": 2, "fail": 0, "skipped": 0}
    _hosted(
        tmp_path,
        "CLM-WEB",
        [evidence, f"reports/release/{RELEASE}/WEB_REGRESSION_REPORT.tap"],
        result,
        monkeypatch,
    )
    (tmp_path / hosted_paths(RELEASE)[0]).unlink()
    assert _status(tmp_path, "CLM-WEB", evidence) == "INVALID_EVIDENCE"
    _write(
        tmp_path / hosted_paths(RELEASE)[0],
        new_attestation(
            tmp_path,
            RELEASE,
            DIGEST,
            {
                candidate: {
                    "executor": executor,
                    "exit_code": 0,
                    "result": result if candidate == "CLM-WEB" else {},
                    "artifacts": [evidence, f"reports/release/{RELEASE}/WEB_REGRESSION_REPORT.tap"]
                    if candidate == "CLM-WEB"
                    else ["reports/release/hosted-test-subject.txt"],
                }
                for candidate, executor in CLAIM_EXECUTORS.items()
            },
        ),
    )
    assert _status(tmp_path, "CLM-WEB", evidence) == "SUPPORTED"
    altered = _web(tmp_path)
    altered["steps"]["test"]["pass"] = 1
    _write(tmp_path / evidence, altered)
    _write(tmp_path / "var/web-regression.json", altered)
    assert _status(tmp_path, "CLM-WEB", evidence) == "INVALID_EVIDENCE"


def test_claim_cannot_redirect_to_synthetic_json(tmp_path: Path) -> None:
    _web_inputs(tmp_path)
    _write(tmp_path / "evidence.json", _web(tmp_path))
    _commit(tmp_path)
    assert _status(tmp_path, "CLM-WEB", "evidence.json") == "INVALID_EVIDENCE"


def test_conflicting_synonymous_source_digests_are_rejected(tmp_path: Path) -> None:
    _web_inputs(tmp_path)
    evidence = f"reports/release/{RELEASE}/WEB_REGRESSION_REPORT.json"
    payload = _web(tmp_path)
    payload["source_tree_sha256"] = DIGEST
    payload["source_digest"] = "b" * 64
    _write(tmp_path / evidence, payload)
    assert _status(tmp_path, "CLM-WEB", evidence) == "DIVERGENT_BINDING"


def _junit(path: Path, *, tests: int = 1, failures: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0"?><testsuites><testsuite '
        f'tests="{tests}" failures="{failures}" errors="0" skipped="0">'
        '<testcase classname="tests.test_sample" name="test_ok"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )


def _backend_tree(root: Path) -> str:
    target = root / "tests/test_sample.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    nodeid = "tests/test_sample.py::test_ok"
    collection = hashlib.sha256(nodeid.encode()).hexdigest()
    selected = hashlib.sha256(nodeid.encode()).hexdigest()
    counts = {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}
    receipt = {
        "schema": "korpus.regression-shard.v1",
        "status": "PASS",
        "release_tag": RELEASE,
        "source_digest": DIGEST,
        "collection_digest": collection,
        "collection_count": 1,
        "shard_index": 0,
        "shard_count": 1,
        "selected_count": 1,
        "selected_nodeids": [nodeid],
        "selected_digest": selected,
        "junit": counts,
        "exit_code": 0,
        "timed_out": False,
        "pytest_args": ["tests/test_sample.py"],
    }
    _write(root / "reports/regression/shards/shard-0.json", receipt)
    _junit(root / "reports/regression/shards/shard-0.junit.xml")
    merge = {
        "schema": "korpus.regression-merge.v1",
        "status": "PASS",
        "release_tag": RELEASE,
        "source_digest": DIGEST,
        "collection_digest": collection,
        "collection_count": 1,
        "shards": 1,
        "junit": counts,
        "failures": [],
        "receipt_paths": ["reports/regression/shards/shard-0.json"],
    }
    _write(root / "reports/regression/FULL_REGRESSION_CURRENT.json", merge)
    evidence = f"reports/release/{RELEASE}/FULL_BACKEND_REPORT.json"
    _write(
        root / evidence,
        {
            "schema": "korpus.full-backend-report.v2",
            "status": "PASS",
            "release": RELEASE,
            "source_tree_sha256": DIGEST,
            "digest_scope": SCOPE,
            "collection_digest": collection,
            "collected": 1,
            "passed": 1,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "shards": 1,
            "evidence_source": "reports/regression/FULL_REGRESSION_CURRENT.json",
        },
    )
    return evidence


def _backend_attestation(root: Path, evidence: str, monkeypatch: pytest.MonkeyPatch | None) -> None:
    _hosted(
        root,
        "CLM-REGRESSION",
        [
            evidence,
            "reports/regression/FULL_REGRESSION_CURRENT.json",
            "reports/regression/shards/shard-0.json",
            "reports/regression/shards/shard-0.junit.xml",
        ],
        {
            "tests": 1,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "collection_digest": hashlib.sha256(b"tests/test_sample.py::test_ok").hexdigest(),
            "shards": 1,
        },
        monkeypatch,
    )


def test_backend_claim_requires_sigstore_attested_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _backend_tree(tmp_path)
    _backend_attestation(tmp_path, evidence, monkeypatch)
    assert _status(tmp_path, "CLM-REGRESSION", evidence) == "SUPPORTED"


def test_fabricated_github_json_is_not_execution_authority(tmp_path: Path) -> None:
    evidence = _backend_tree(tmp_path)
    _backend_attestation(tmp_path, evidence, None)
    assert _status(tmp_path, "CLM-REGRESSION", evidence) == "INVALID_EVIDENCE"


def test_sigstore_verifier_ignores_path_hijack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "gh"
    marker = tmp_path / "executed"
    fake.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")

    executable, reason = verifier_executable(Path(__file__).resolve().parents[3])

    assert (executable, reason) == ("/usr/bin/gh", None)
    assert not marker.exists()


def test_sigstore_verifier_rejects_digest_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "korpus.application.release_claim_sigstore.sha256_bytes", lambda _payload: "0" * 64
    )
    assert verifier_executable(Path(__file__).resolve().parents[3]) == (
        None,
        "SIGSTORE_VERIFIER_DIGEST_MISMATCH",
    )


def test_sigstore_verifier_rejects_mutable_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = os.lstat("/usr/bin/gh")
    poisoned = os.stat_result((observed.st_mode | stat.S_IWGRP, *tuple(observed)[1:]))
    monkeypatch.setattr(
        "korpus.application.release_claim_sigstore.os.lstat", lambda _path: poisoned
    )
    assert verifier_executable(Path(__file__).resolve().parents[3]) == (
        None,
        "SIGSTORE_VERIFIER_MUTABLE",
    )


@pytest.mark.parametrize("poison", ["digest", "junit", "source"])
def test_backend_claim_rejects_lying_projection(
    tmp_path: Path, poison: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _backend_tree(tmp_path)
    _backend_attestation(tmp_path, evidence, monkeypatch)
    if poison == "digest":
        receipt_path = tmp_path / "reports/regression/shards/shard-0.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["selected_digest"] = "0" * 64
        _write(receipt_path, receipt)
    elif poison == "junit":
        _junit(tmp_path / "reports/regression/shards/shard-0.junit.xml", failures=1)
    else:
        report_path = tmp_path / evidence
        report = json.loads(report_path.read_text())
        report["evidence_source"] = "missing.json"
        _write(report_path, report)
    assert _status(tmp_path, "CLM-REGRESSION", evidence) == "INVALID_EVIDENCE"


def _mutation_tree(root: Path) -> str:
    runner = root / "scripts/run_mutation_tests.py"
    runner.parent.mkdir(parents=True)
    runner.write_text(
        'MUTANTS = (Mutant("M1", "apps/api/src/korpus/a.py", "old", "new", '
        '("tests/test_a.py::test_a",)),)\n',
        encoding="utf-8",
    )
    source = root / "apps/api/src/korpus/a.py"
    source.parent.mkdir(parents=True)
    source.write_text("old = True\n", encoding="utf-8")
    test = root / "tests/test_a.py"
    test.parent.mkdir(parents=True)
    test.write_text("def test_a():\n    assert True\n", encoding="utf-8")
    report = {
        "schema_version": 3,
        "status": "PASS",
        "release": RELEASE,
        "shard_index": None,
        "shard_count": 1,
        "mutants": 1,
        "valid_mutants": 1,
        "killed": 1,
        "survived": [],
        "invalid": [],
        "errors": [],
        "mutation_score": 1.0,
        "mutation_score_over_catalogue": 1.0,
        "results": [
            {
                "id": "M1",
                "file": "apps/api/src/korpus/a.py",
                "status": "KILLED",
                "returncode": 1,
                "target_occurrences": 1,
                "tests": ["tests/test_a.py::test_a"],
                "sandbox_mode": "api_source_overlay",
            }
        ],
        "provenance": {
            "schema_version": 1,
            "source_digest": DIGEST,
            "digest_scope": SCOPE,
            "generator": "scripts/run_mutation_tests.py",
            "generated_at": "2026-10-19T00:00:00+00:00",
        },
    }
    evidence = "reports/MUTATION_FULL_CATALOGUE_CURRENT.json"
    _write(root / evidence, report)
    _write(root / "reports/MUTATION_REPORT.json", report)
    return evidence


def _mutation_attestation(root: Path, evidence: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _hosted(
        root,
        "CLM-MUTATION",
        [evidence, "reports/MUTATION_REPORT.json"],
        {
            "mutants": 1,
            "killed": 1,
            "survived": [],
            "invalid": [],
            "errors": [],
            "mutation_score": 1.0,
        },
        monkeypatch,
    )


def test_mutation_claim_matches_code_catalogue_and_portable_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _mutation_tree(tmp_path)
    _mutation_attestation(tmp_path, evidence, monkeypatch)
    assert _status(tmp_path, "CLM-MUTATION", evidence) == "SUPPORTED"
    (tmp_path / "reports/MUTATION_REPORT.json").unlink()
    assert _status(tmp_path, "CLM-MUTATION", evidence) == "INVALID_EVIDENCE"


def test_mutation_claim_rejects_result_identity_forgery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _mutation_tree(tmp_path)
    _mutation_attestation(tmp_path, evidence, monkeypatch)
    for path in (tmp_path / evidence, tmp_path / "reports/MUTATION_REPORT.json"):
        report = json.loads(path.read_text())
        report["results"][0]["tests"] = ["tests/test_other.py::test_other"]
        _write(path, report)
    assert _status(tmp_path, "CLM-MUTATION", evidence) == "INVALID_EVIDENCE"


INFERENCE_CHECKS = {
    "profile_gate_id",
    "evidence_class_internal_adversarial",
    "attack_families_nonempty",
    "attack_families_unique",
    "pytest_targets_nonempty",
    "pytest_targets_unique",
    "pytest_targets_exist",
    "family_target_mapping_complete",
    "every_family_has_executable_target",
    "family_targets_declared_in_suite",
    "family_targets_exist",
    "pytest_exit_zero",
    "tests_executed",
    "no_test_failures",
    "no_test_errors",
    "no_test_skips",
}


def _inference_tree(root: Path) -> str:
    target = "tests/test_inference.py"
    (root / target).parent.mkdir(parents=True)
    (root / target).write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    profile = {
        "gate_id": "inference_security",
        "evidence_class": "INTERNAL_ADVERSARIAL",
        "attack_families": ["injection"],
        "pytest_targets": [target],
        "family_targets": {"injection": [target]},
    }
    profile_path = root / "config/assurance/inference-security-v1.json"
    _write(profile_path, profile)
    script = root / "scripts/run_inference_security_gate.py"
    script.parent.mkdir(parents=True)
    script.write_text("# canonical producer\n", encoding="utf-8")
    junit = root / f"reports/release/{RELEASE}/INFERENCE_SECURITY_GATE.junit.xml"
    _junit(junit)
    report = {
        "schema": "korpus.production-gate.v1",
        "gate_id": "inference_security",
        "status": "PASS",
        "source_tree_sha256": DIGEST,
        "digest_scope": SCOPE,
        "release": RELEASE,
        "checks": {name: True for name in INFERENCE_CHECKS},
        "failures": [],
        "evidence_class": "INTERNAL_ADVERSARIAL",
        "profile": "config/assurance/inference-security-v1.json",
        "profile_sha256": _sha(profile_path),
        "attack_families": ["injection"],
        "pytest_targets": [target],
        "pytest_exit_code": 0,
        "pytest": {"tests": 1, "failures": 0, "errors": 0, "skipped": 0},
        "junit_sha256": _sha(junit),
    }
    evidence = f"reports/release/{RELEASE}/INFERENCE_SECURITY_GATE.json"
    _write(root / evidence, report)
    _write(root / "var/production/inference_security-gate.json", report)
    return evidence


def _inference_attestation(root: Path, evidence: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _hosted(
        root,
        "CLM-INFERENCE-SECURITY",
        [evidence, f"reports/release/{RELEASE}/INFERENCE_SECURITY_GATE.junit.xml"],
        {"tests": 1, "failures": 0, "errors": 0, "skipped": 0},
        monkeypatch,
    )


def test_inference_claim_binds_profile_producer_and_junit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _inference_tree(tmp_path)
    _inference_attestation(tmp_path, evidence, monkeypatch)
    assert _status(tmp_path, "CLM-INFERENCE-SECURITY", evidence) == "SUPPORTED"
    _junit(tmp_path / f"reports/release/{RELEASE}/INFERENCE_SECURITY_GATE.junit.xml", tests=2)
    assert _status(tmp_path, "CLM-INFERENCE-SECURITY", evidence) == "INVALID_EVIDENCE"


def test_inference_claim_rejects_changed_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _inference_tree(tmp_path)
    _inference_attestation(tmp_path, evidence, monkeypatch)
    profile = tmp_path / "config/assurance/inference-security-v1.json"
    value = json.loads(profile.read_text())
    value["attack_families"] = ["other"]
    _write(profile, value)
    assert _status(tmp_path, "CLM-INFERENCE-SECURITY", evidence) == "INVALID_EVIDENCE"


@pytest.mark.parametrize("claim_id", ["CLM-PRODUCTION-AUTH", "CLM-INDEPENDENT"])
def test_blocker_self_report_cannot_authorize_production(tmp_path: Path, claim_id: str) -> None:
    evidence = f"reports/release/{RELEASE}/final/BLOCKER_REGISTRY.json"
    _write(
        tmp_path / evidence,
        {
            "schema": "korpus.blocker-registry.v2",
            "release": RELEASE,
            "status": "PASS",
            "source_tree_sha256": DIGEST,
            "digest_scope": SCOPE,
            "items": [],
            "counts": {},
            "internal_executable_unresolved": 0,
            "production_external_or_runtime_unresolved": 0,
        },
    )
    _commit(tmp_path)
    assert _status(tmp_path, claim_id, evidence) == "INVALID_EVIDENCE"
