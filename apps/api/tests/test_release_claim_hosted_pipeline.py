from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from korpus.application.github_assurance_receipts import new_receipt
from korpus.application.provenance import compute_source_digest
from korpus.application.release_claim_hosted import CLAIM_EXECUTORS, new_attestation
from korpus.application.release_claim_tree import tracked_tree_digest

from scripts import build_release_claim_evidence as producer
from scripts import import_release_claim_evidence as importer
from scripts import publish_web_regression as web
from scripts import release_claim_projection as claim_projection

ROOT = Path(__file__).resolve().parents[3]


def _commit_all(root: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=KORPUS test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            message,
        ],
        check=True,
    )


def test_tracked_tree_digest_ignores_archive_attributes(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitattributes").write_text(
        "hidden.py export-ignore\nabout.txt export-subst\n", encoding="utf-8"
    )
    (tmp_path / "hidden.py").write_text("secret = 1\n", encoding="utf-8")
    (tmp_path / "about.txt").write_text("commit=$Format:%H$\n", encoding="utf-8")
    _commit_all(tmp_path, "initial")
    initial = tracked_tree_digest(tmp_path)

    (tmp_path / "hidden.py").write_text("secret = 'changed'\n", encoding="utf-8")
    _commit_all(tmp_path, "change export-ignored source")
    changed = tracked_tree_digest(tmp_path)
    assert changed is not None and changed != initial

    report = tmp_path / "reports/evidence.json"
    report.parent.mkdir()
    report.write_text("{}\n", encoding="utf-8")
    _commit_all(tmp_path, "excluded evidence only")
    assert tracked_tree_digest(tmp_path) == changed


def test_tracked_tree_digest_ignores_path_git_shims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    (repository / "source.py").write_text("answer = 42\n", encoding="utf-8")
    _commit_all(repository, "source")
    expected = tracked_tree_digest(repository)
    shim = tmp_path / "git"
    marker = tmp_path / "path-git-executed"
    shim.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n", encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert tracked_tree_digest(repository) == expected
    assert not marker.exists()


def _tap(*, tests: int = 2, passed: int = 2, failed: int = 0, skipped: int = 0) -> bytes:
    assertions = [f"ok {index} - passing {index}" for index in range(1, passed + 1)]
    assertions.extend(
        f"not ok {index} - failing {index}" for index in range(passed + 1, passed + failed + 1)
    )
    assertions.extend(
        f"ok {index} - skipped {index} # SKIP"
        for index in range(passed + failed + 1, passed + failed + skipped + 1)
    )
    return (
        "\n".join(
            [
                "TAP version 13",
                *assertions,
                f"1..{tests}",
                f"# tests {tests}",
                f"# pass {passed}",
                f"# fail {failed}",
                f"# skipped {skipped}",
                "",
            ]
        )
    ).encode()


def _provenance(generator: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_digest": "a" * 64,
        "digest_scope": "evidence_paths",
        "generator": generator,
        "generated_at": "2026-10-19T00:00:00+00:00",
    }


def _web_payload(test_output: bytes) -> dict[str, object]:
    counts = {"tests": 2, "pass": 2, "fail": 0, "skipped": 0}
    return {
        "schema": "korpus.web-regression.v1",
        "release": "v-test",
        "status": "PASS",
        "steps": {
            "lint": {"exit_code": 0, "status": "PASS"},
            "test": {"exit_code": 0, "status": "PASS", **counts},
            "build": {"exit_code": 0, "status": "PASS"},
        },
        "tests": 2,
        "passed": 2,
        "failed": 0,
        "skipped": 0,
        "test_output_sha256": hashlib.sha256(test_output).hexdigest(),
        "evidence_class": "LOCAL_NODE_TEST_RUNNER",
        "provenance": _provenance("scripts/publish_web_regression.py"),
    }


def _mutation_payload() -> dict[str, object]:
    return {
        "schema_version": 3,
        "status": "PASS",
        "release": "v0.9.7",
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
        "provenance": _provenance("scripts/run_mutation_tests.py"),
        "results": [
            {
                "id": "M1",
                "file": "source.py",
                "status": "KILLED",
                "returncode": 1,
                "target_occurrences": 1,
                "tests": ["test_source.py::test_guard"],
                "sandbox_mode": "full_copy",
                "output_tail": "runtime noise",
            }
        ],
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_provenance_refuses_boolean_schema_version() -> None:
    provenance = _provenance("scripts/run_mutation_tests.py")
    provenance["schema_version"] = True
    assert not producer._provenance(
        {"provenance": provenance}, "a" * 64, "scripts/run_mutation_tests.py"
    )


def test_web_publisher_writes_exact_fresh_test_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_output = _tap()
    outputs = {"lint": b"lint\n", "test": test_output, "build": b"build\n"}
    monkeypatch.setattr(web, "_run", lambda name: (0, outputs[name]))
    monkeypatch.setattr(web, "release_tag", lambda _root: "v-test")
    monkeypatch.setattr(
        web,
        "stamp",
        lambda _root, generator: {
            "schema_version": 1,
            "source_digest": "a" * 64,
            "digest_scope": "evidence_paths",
            "generator": generator,
            "generated_at": "2026-10-19T00:00:00+00:00",
        },
    )
    report, tap = tmp_path / "web.json", tmp_path / "web.tap"

    assert web.main(["--out", str(report), "--tap-out", str(tap)]) == 0

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert tap.read_bytes() == test_output
    assert payload["test_output_sha256"] == hashlib.sha256(test_output).hexdigest()
    assert payload["steps"]["test"] == {
        "exit_code": 0,
        "status": "PASS",
        "tests": 2,
        "pass": 2,
        "fail": 0,
        "skipped": 0,
    }
    canonical = tmp_path / "reports/release/v-test"
    canonical.mkdir(parents=True)
    (canonical / "WEB_REGRESSION_REPORT.json").write_bytes(report.read_bytes())
    (canonical / "WEB_REGRESSION_REPORT.tap").write_bytes(tap.read_bytes())
    monkeypatch.setattr(producer, "_tracked", lambda _root, _paths: None)
    execution = producer._web_execution(tmp_path, "v-test", "a" * 64, report, tap)
    assert execution["result"] == {"tests": 2, "pass": 2, "fail": 0, "skipped": 0}


@pytest.mark.parametrize(
    "poison",
    [
        "schema",
        "evidence_class",
        "lint_exit",
        "lint_bool_exit",
        "lint_status",
        "test_exit",
        "test_bool_count",
        "test_status",
        "build_exit",
        "build_status",
        "extra_step_field",
        "top_level_totals",
        "bool_top_level_total",
    ],
)
def test_web_execution_validator_rejects_false_pass_fields(poison: str) -> None:
    test_output = _tap()
    payload = _web_payload(test_output)
    counts = {"tests": 2, "pass": 2, "fail": 0, "skipped": 0}
    digest = hashlib.sha256(test_output).hexdigest()
    assert claim_projection.web_execution_valid(payload, "v-test", counts, digest)

    poisoned = json.loads(json.dumps(payload))
    if poison == "schema":
        poisoned["schema"] = "korpus.web-regression.v0"
    elif poison == "evidence_class":
        poisoned["evidence_class"] = "SELF_REPORTED"
    elif poison == "top_level_totals":
        poisoned.update({"tests": 999, "passed": 998, "failed": 1})
    elif poison == "bool_top_level_total":
        poisoned["failed"] = False
    elif poison == "extra_step_field":
        poisoned["steps"]["lint"]["extra"] = 1
    elif poison == "lint_bool_exit":
        poisoned["steps"]["lint"]["exit_code"] = False
    elif poison == "test_bool_count":
        poisoned["steps"]["test"]["fail"] = False
    else:
        step, field = poison.split("_", maxsplit=1)
        poisoned["steps"][step][field] = 1 if field == "exit" else "FAIL"
        if field == "exit":
            poisoned["steps"][step]["exit_code"] = poisoned["steps"][step].pop("exit")
    assert not claim_projection.web_execution_valid(poisoned, "v-test", counts, digest)


def test_web_execution_refuses_contradictory_pass_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_output = _tap()
    payload = _web_payload(test_output)
    payload["steps"]["lint"] = {"exit_code": 1, "status": "FAIL"}
    payload["steps"]["build"] = {"exit_code": 1, "status": "FAIL"}
    payload.update({"tests": 999, "passed": 998, "failed": 1})
    actual = tmp_path / "actual-web.json"
    actual_tap = tmp_path / "actual-web.tap"
    canonical = tmp_path / "reports/release/v-test/WEB_REGRESSION_REPORT.json"
    canonical_tap = tmp_path / "reports/release/v-test/WEB_REGRESSION_REPORT.tap"
    _write_json(actual, payload)
    _write_json(canonical, payload)
    actual_tap.write_bytes(test_output)
    canonical_tap.write_bytes(test_output)
    monkeypatch.setattr(producer, "_tracked", lambda _root, _paths: None)

    with pytest.raises(ValueError, match="canonical web evidence"):
        producer._web_execution(tmp_path, "v-test", "a" * 64, actual, actual_tap)


def test_release_publisher_refuses_unbound_execution_companions(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    source = tmp_path / "execution.tap"
    destination = tmp_path / "published.tap"
    source.write_bytes(_tap())
    report.write_text(
        json.dumps({"test_output_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}),
        encoding="utf-8",
    )
    assert (
        claim_projection.publish_companion(destination, report, source, "test_output_sha256")
        is None
    )
    assert destination.read_bytes() == source.read_bytes()

    source.write_bytes(_tap(tests=3, passed=3))
    assert "does not bind" in str(
        claim_projection.publish_companion(destination, report, source, "test_output_sha256")
    )
    assert not destination.exists()


def test_tap_parser_refuses_duplicate_or_inconsistent_summaries(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.tap"
    duplicate.write_bytes(_tap() + b"# tests 2\n")
    with pytest.raises(ValueError, match="summaries"):
        producer._tap(duplicate)

    inconsistent = tmp_path / "inconsistent.tap"
    inconsistent.write_bytes(_tap(tests=3, passed=2))
    with pytest.raises(ValueError, match="arithmetically invalid"):
        producer._tap(inconsistent)

    summary_only = tmp_path / "summary-only.tap"
    summary_only.write_text(
        "TAP version 13\n1..0\n# tests 2\n# pass 2\n# fail 0\n# skipped 0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="arithmetically invalid"):
        producer._tap(summary_only)

    bailout = tmp_path / "bailout.tap"
    bailout.write_bytes(_tap() + b"Bail out! catastrophic harness abort\n")
    with pytest.raises(ValueError, match="arithmetically invalid"):
        producer._tap(bailout)


def test_junit_parser_refuses_counters_without_testcases(tmp_path: Path) -> None:
    counters_only = tmp_path / "counters-only.xml"
    counters_only.write_text(
        '<testsuite tests="2" failures="0" errors="0" skipped="0"/>\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="structurally inconsistent"):
        producer._junit(counters_only)

    valid = tmp_path / "valid.xml"
    valid.write_text(
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="tests.test_guard" name="test_guard"/>'
        "</testsuite>\n",
        encoding="utf-8",
    )
    assert producer._junit(valid) == {
        "tests": 1,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
    }


def test_mutation_comparison_ignores_only_runtime_noise() -> None:
    base = {
        "schema_version": 3,
        "status": "PASS",
        "release": "v0.9.7",
        "shard_index": None,
        "shard_count": 6,
        "mutants": 1,
        "valid_mutants": 1,
        "killed": 1,
        "survived": [],
        "invalid": [],
        "errors": [],
        "mutation_score": 1.0,
        "mutation_score_over_catalogue": 1.0,
        "provenance": {
            "schema_version": 1,
            "source_digest": "a" * 64,
            "digest_scope": "evidence_paths",
            "generator": "scripts/run_mutation_tests.py",
            "generated_at": "first",
        },
        "results": [
            {
                "id": "M1",
                "file": "source.py",
                "status": "KILLED",
                "returncode": 1,
                "target_occurrences": 1,
                "tests": ["test_source.py::test_guard"],
                "sandbox_mode": "full_copy",
                "output_tail": "nondeterministic first run",
            }
        ],
    }
    replay = json.loads(json.dumps(base))
    replay["provenance"]["generated_at"] = "second"
    replay["results"][0]["output_tail"] = "nondeterministic second run"
    assert producer._mutation_projection(base) == producer._mutation_projection(replay)

    replay["results"][0]["target_occurrences"] = 0
    assert producer._mutation_projection(base) != producer._mutation_projection(replay)


@pytest.mark.parametrize(
    "poison",
    [
        "valid_mutants_zero",
        "bool_mutants",
        "unequal_counts",
        "nonempty_survived",
        "mutation_score",
        "catalogue_score",
        "result_status",
        "bool_returncode",
        "bool_target_occurrences",
        "duplicate_id",
        "empty_results",
    ],
)
def test_mutation_execution_validator_rejects_false_pass_fields(poison: str) -> None:
    payload = _mutation_payload()
    assert claim_projection.mutation_execution_valid(payload)
    poisoned = json.loads(json.dumps(payload))
    if poison == "valid_mutants_zero":
        poisoned["valid_mutants"] = 0
    elif poison == "bool_mutants":
        poisoned["mutants"] = True
    elif poison == "unequal_counts":
        poisoned["killed"] = 2
    elif poison == "nonempty_survived":
        poisoned["survived"] = ["M1"]
    elif poison == "mutation_score":
        poisoned["mutation_score"] = 0.0
    elif poison == "catalogue_score":
        poisoned["mutation_score_over_catalogue"] = True
    elif poison == "result_status":
        poisoned["results"][0]["status"] = "SURVIVED"
    elif poison == "bool_returncode":
        poisoned["results"][0]["returncode"] = True
    elif poison == "bool_target_occurrences":
        poisoned["results"][0]["target_occurrences"] = True
    elif poison == "duplicate_id":
        poisoned["results"].append(dict(poisoned["results"][0]))
        poisoned.update({"mutants": 2, "valid_mutants": 2, "killed": 2})
    else:
        poisoned["results"] = []
    assert not claim_projection.mutation_execution_valid(poisoned)


def test_mutation_execution_refuses_internally_inconsistent_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _mutation_payload()
    payload.update(
        {
            "valid_mutants": 0,
            "mutation_score": 0.0,
            "mutation_score_over_catalogue": 0.0,
        }
    )
    actual = tmp_path / "actual-mutation.json"
    canonical = tmp_path / "reports/MUTATION_FULL_CATALOGUE_CURRENT.json"
    alias = tmp_path / "reports/MUTATION_REPORT.json"
    _write_json(actual, payload)
    _write_json(canonical, payload)
    _write_json(alias, payload)
    monkeypatch.setattr(producer, "_tracked", lambda _root, _paths: None)

    with pytest.raises(ValueError, match="canonical mutation evidence"):
        producer._mutation_execution(tmp_path, "a" * 64, actual)


def test_main_push_lane_reuses_heavy_jobs_and_attests_exact_payload() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/assurance.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["release-claims"]
    condition = job["if"]
    assert "github.event_name == 'push'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "refs/heads/integration/canonical-convergence-" in condition
    assert "pull_request" not in condition
    assert set(job["needs"]) == {"research-assurance", "sqlite-coverage"}
    assert job["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
    }
    actions = {step.get("uses") for step in job["steps"]}
    assert "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1" in actions
    assert "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8" in actions
    runs = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "build_release_claim_evidence.py" in runs
    assert "publish_web_regression.py" in runs
    assert "npm --prefix apps/web ci --ignore-scripts --no-audit --no-fund" in runs
    assert "run_mutation" not in runs
    assert "make api-test" not in runs
    assert "RELEASE_CLAIM_ATTESTATION.sigstore.json" in str(job)
    assert "release-claim-evidence" in str(job)

    research = workflow["jobs"]["research-assurance"]
    assert "var/production/inference_security-gate.json" in str(research)
    assert "var/production/inference_security.pytest.xml" in str(research)

    assert producer.allowed_source_ref("refs/heads/main")
    assert producer.allowed_source_ref("refs/heads/integration/canonical-convergence-20261019-v2")
    assert not producer.allowed_source_ref("refs/heads/integration/arbitrary")


def test_importer_transport_uses_the_pinned_gh_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        observed.append(command)
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(importer, "verifier_executable", lambda _root: ("/usr/bin/gh", None))
    monkeypatch.setattr(importer.subprocess, "run", run)
    assert importer._gh_json("repos/neuron7x/KORPUS") == {"ok": True}
    assert observed == [["/usr/bin/gh", "api", "repos/neuron7x/KORPUS"]]


def test_importer_rejects_a_bundle_when_the_pinned_verifier_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importer, "verify_sigstore_bundle", lambda *_args: False)
    with pytest.raises(ValueError, match="Sigstore verification failed"):
        importer._verify_sigstore(
            tmp_path,
            tmp_path / "attestation.json",
            tmp_path / "bundle.json",
            "a" * 40,
            "refs/heads/main",
        )


def test_importer_binds_bundle_admission_to_exact_local_artifacts(tmp_path: Path) -> None:
    release = "v1.2.3"
    paths = {
        f"reports/release/{release}/FULL_BACKEND_REPORT.json": b"{}\n",
        "reports/regression/FULL_REGRESSION_CURRENT.json": b'{"shards":1}\n',
        "reports/regression/shards/shard-0.json": b"{}\n",
        "reports/regression/shards/shard-0.junit.xml": b'<testsuite tests="1"/>\n',
        f"reports/release/{release}/WEB_REGRESSION_REPORT.json": b"{}\n",
        f"reports/release/{release}/WEB_REGRESSION_REPORT.tap": _tap(tests=1, passed=1),
        "reports/MUTATION_FULL_CATALOGUE_CURRENT.json": b"{}\n",
        "reports/MUTATION_REPORT.json": b"{}\n",
        f"reports/release/{release}/INFERENCE_SECURITY_GATE.json": b"{}\n",
        f"reports/release/{release}/INFERENCE_SECURITY_GATE.junit.xml": b'<testsuite tests="1"/>\n',
        "apps/api/src/korpus/release.json": json.dumps(
            {
                "schema": "korpus.release-identity.v1",
                "product": "KORPUS",
                "version": "1.2.3",
                "tag": release,
                "artifact_stem": "KORPUS",
                "distribution_artifact": "KORPUS.zip",
            }
        ).encode(),
    }
    for relative, payload in paths.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=KORPUS test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source = compute_source_digest(tmp_path)
    executions = {
        "CLM-REGRESSION": {
            "executor": "backend",
            "exit_code": 0,
            "result": {"tests": 1},
            "artifacts": [
                f"reports/release/{release}/FULL_BACKEND_REPORT.json",
                "reports/regression/FULL_REGRESSION_CURRENT.json",
                "reports/regression/shards/shard-0.json",
                "reports/regression/shards/shard-0.junit.xml",
            ],
        },
        "CLM-WEB": {
            "executor": "web",
            "exit_code": 0,
            "result": {"tests": 1},
            "artifacts": [
                f"reports/release/{release}/WEB_REGRESSION_REPORT.json",
                f"reports/release/{release}/WEB_REGRESSION_REPORT.tap",
            ],
        },
        "CLM-MUTATION": {
            "executor": "mutation",
            "exit_code": 0,
            "result": {"mutants": 1},
            "artifacts": [
                "reports/MUTATION_FULL_CATALOGUE_CURRENT.json",
                "reports/MUTATION_REPORT.json",
            ],
        },
        "CLM-INFERENCE-SECURITY": {
            "executor": "inference",
            "exit_code": 0,
            "result": {"tests": 1},
            "artifacts": [
                f"reports/release/{release}/INFERENCE_SECURITY_GATE.json",
                f"reports/release/{release}/INFERENCE_SECURITY_GATE.junit.xml",
            ],
        },
    }
    assert set(executions) == set(CLAIM_EXECUTORS)
    attestation = new_attestation(
        tmp_path, release, source, executions, source_ref="refs/heads/main"
    )
    attestation_bytes = (json.dumps(attestation, indent=2) + "\n").encode()
    identity = {
        "repository": "neuron7x/KORPUS",
        "repository_id": 1_332_311_807,
        "repository_owner_id": 206_596_321,
        "workflow_id": 332_983_284,
        "workflow_path": ".github/workflows/assurance.yml",
        "run_id": 42,
        "run_attempt": 1,
        "commit_sha": commit,
    }
    subjects = {
        "release-claims": {
            "release": release,
            "source_tree_sha256": source,
            "digest_scope": "evidence_paths",
            "tracked_tree_sha256": attestation["tracked_tree_sha256"],
            "source_ref": "refs/heads/main",
            "claims": sorted(CLAIM_EXECUTORS),
        }
    }
    receipt = new_receipt(
        identity,
        kind="release-claims",
        job="release-claims",
        source_tree_sha256=attestation["tracked_tree_sha256"],
        artifacts={importer.ATTESTATION_NAME: attestation_bytes},
        subjects=subjects,
    )
    files = {
        importer.ATTESTATION_NAME: attestation_bytes,
        importer.RECEIPT_NAME: (json.dumps(receipt, indent=2) + "\n").encode(),
        importer.BUNDLE_NAME: b"signed-bundle",
    }
    verified: list[tuple[str, str]] = []

    def verifier(
        _root: Path, attestation_path: Path, bundle_path: Path, observed: str, ref: str
    ) -> None:
        assert attestation_path.read_bytes() == attestation_bytes
        assert bundle_path.read_bytes() == b"signed-bundle"
        verified.append((observed, ref))

    admission = importer.validate_downloaded(
        tmp_path,
        identity,
        17,
        files,
        source_ref="refs/heads/main",
        verifier=verifier,
    )
    assert verified == [(commit, "refs/heads/main")]
    assert admission["artifacts"]["release-claim-evidence"]["artifact_id"] == 17

    malformed_claim_sets = [
        {},
        {
            claim_id: claim
            for claim_id, claim in attestation["claims"].items()
            if claim_id != "CLM-WEB"
        },
        {**attestation["claims"], "CLM-UNDECLARED": attestation["claims"]["CLM-WEB"]},
    ]
    for claims in malformed_claim_sets:
        malformed = {**attestation, "claims": claims}
        malformed_files = {
            **files,
            importer.ATTESTATION_NAME: (json.dumps(malformed, indent=2) + "\n").encode(),
        }
        with pytest.raises(ValueError, match="claim set"):
            importer.validate_downloaded(
                tmp_path,
                identity,
                17,
                malformed_files,
                source_ref="refs/heads/main",
                verifier=verifier,
            )

    (tmp_path / f"reports/release/{release}/WEB_REGRESSION_REPORT.json").write_text(
        '{"tampered":true}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="CLM-WEB"):
        importer.validate_downloaded(
            tmp_path,
            identity,
            17,
            files,
            source_ref="refs/heads/main",
            verifier=verifier,
        )
