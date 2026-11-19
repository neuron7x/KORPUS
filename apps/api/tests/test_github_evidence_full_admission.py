"""The public path admits all hosted subjects from one immutable network capture."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import await_github_evidence as wait_cli  # noqa: E402
import github_evidence_import as importer  # noqa: E402
import github_evidence_publication as publication  # noqa: E402
import github_security_admission as security_admission  # noqa: E402
import import_github_evidence as direct_cli  # noqa: E402
from github_evidence_artifact import digest  # noqa: E402
from github_evidence_run import PACKAGE, SECURITY, Producer  # noqa: E402
from github_package_admission import package_producer  # noqa: E402
from github_source_identity import IDENTITY_PATHS  # noqa: E402

from .hosted_evidence_fixtures import (  # noqa: E402
    SELECTED,
    EvidenceFixture,
    encoded,
    measured_fixture,
    with_security,
)


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> EvidenceFixture:
    return with_security(measured_fixture(tmp_path_factory.mktemp("hosted-complete")))


def _wire(monkeypatch, fixture: EvidenceFixture) -> None:
    monkeypatch.setattr(importer, "capture_checkout", lambda root: fixture.checkout)
    monkeypatch.setattr(importer, "GitHubTransport", lambda: fixture.api)


def _receipt(fixture: EvidenceFixture, change) -> None:
    name = "source-security-receipt.json"
    value = json.loads(fixture.members[SECURITY.job][name])
    change(value)
    fixture.members[SECURITY.job][name] = encoded(value)
    fixture.repack(SECURITY)


def _member(fixture: EvidenceFixture, name: str, payload: bytes) -> None:
    fixture.members[SECURITY.job][name] = payload
    _receipt(fixture, lambda receipt: receipt["artifacts"][name].update(sha256=digest(payload)))


def test_complete_live_capture_preserves_exact_zip_members_and_publishes_projection(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = measured.clone()
    _wire(monkeypatch, fixture)
    evidence = importer.fetch_evidence(fixture.checkout.root, SELECTED)
    assert evidence.receipt["subjects"] == [
        "sqlite",
        "postgresql",
        "source-sbom",
        "source-scanners",
    ]
    assert (
        evidence.receipt["production_authorized"] is evidence.receipt["signature_verified"] is False
    )
    for artifact in evidence.artifacts:
        assert (
            artifact.zip_bytes
            == fixture.api.responses[f"/actions/artifacts/{artifact.artifact_id}/zip"]
        )
        assert artifact.members == fixture.members[artifact.producer_job_name]
        assert fixture.api.downloads.count(f"/actions/artifacts/{artifact.artifact_id}/zip") == 1
    assert evidence.coverage_projection("v0.9.7")["branch_coverage_percent"] == 100
    with pytest.raises(dataclasses.FrozenInstanceError):
        evidence.identity.head_sha = "f" * 40
    diagnostic = evidence.receipt
    diagnostic["identity"]["repository_id"] = 1
    assert evidence.receipt["identity"]["repository_id"] != 1
    source = "apps/api/src/korpus/toy.py"
    assert evidence.source_members[source] == (fixture.checkout.root / source).read_bytes()
    with pytest.raises(TypeError):
        evidence.source_members[source] = b"replacement source"
    assert tuple(evidence.source_identity_members) == IDENTITY_PATHS
    for name in IDENTITY_PATHS:
        assert evidence.source_identity_members[name] == evidence.source_members[name]
    with pytest.raises(TypeError):
        evidence.source_identity_members["SOURCE_MANIFEST.json"] = b"forged identity"


def test_release_projection_calls_fresh_full_admission_and_does_not_read_saved_pass(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = measured.clone()
    _wire(monkeypatch, fixture)
    monkeypatch.setenv("KORPUS_EVIDENCE_RUN_ID", str(SELECTED.run_id))
    monkeypatch.setenv("KORPUS_EVIDENCE_RUN_ATTEMPT", str(SELECTED.attempt))
    monkeypatch.setenv("KORPUS_EVIDENCE_REF", SELECTED.ref)
    report = publication.admitted_coverage_projection(fixture.checkout.root, ("c" * 64, "v0.9.7"))
    assert report["source_tree_sha256"] == "c" * 64 and report["branch_coverage_percent"] == 100
    assert len(fixture.api.downloads) == 6


def test_publisher_release_binding_uses_captured_bytes_after_live_admission(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = measured.clone()
    _wire(monkeypatch, fixture)
    evidence = importer.fetch_evidence(fixture.checkout.root, SELECTED)
    monkeypatch.setattr(publication, "fetch_evidence", lambda root, selected: evidence)
    for name, value in zip(publication.SELECTOR_FIELDS, ("12345", "2", SELECTED.ref), strict=True):
        monkeypatch.setenv(name, value)
    path = fixture.checkout.root / "apps/api/src/korpus/release.json"
    original = path.read_bytes()
    path.write_bytes(b'{"tag":"v0.0.0"}')
    try:
        assert (
            publication.admitted_coverage_projection(fixture.checkout.root, ("c" * 64, "v0.9.7"))[
                "release"
            ]
            == "v0.9.7"
        )
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize("cli", [direct_cli, wait_cli])
def test_cli_persists_only_fresh_admitted_bytes_and_revokes_stale_success(
    monkeypatch, tmp_path, measured: EvidenceFixture, cli
) -> None:
    fixture = measured.clone()
    _wire(monkeypatch, fixture)
    arguments = [
        "evidence",
        "--source-root",
        str(fixture.checkout.root),
        "--ref",
        SELECTED.ref,
        "--out",
        str(tmp_path),
    ]
    if cli is direct_cli:
        arguments += ["--run-id", "12345", "--run-attempt", "2"]
    else:
        monkeypatch.setattr(wait_cli, "wait_for_selection", lambda *args: SELECTED)
    monkeypatch.setattr(sys, "argv", arguments)
    assert cli.main() == 0
    assert (
        json.loads((tmp_path / "github-evidence-admission.json").read_bytes())["status"] == "PASS"
    )

    def refused(*args):
        raise ValueError("explicit live capture refusal")

    monkeypatch.setattr(cli, "fetch_evidence", refused)
    assert cli.main() == 1
    assert not (tmp_path / "github-evidence-admission.json").exists()
    assert not (tmp_path / "coverage-union.json").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_commit_sha", "f" * 40),
        ("source_tree_oid", "f" * 40),
        ("source_after_sha256", "f" * 64),
        ("status", "FAIL"),
        ("production_authorized", True),
    ],
)
def test_coherent_security_archive_cannot_rebind_its_source_or_verdict(
    monkeypatch, measured: EvidenceFixture, field: str, value
) -> None:
    fixture = measured.clone()
    _receipt(fixture, lambda record: record.update({field: value}))
    _wire(monkeypatch, fixture)
    with pytest.raises(ValueError):
        importer.fetch_evidence(fixture.checkout.root, SELECTED)


@pytest.mark.parametrize(
    "poison",
    ["wrong_attempt", "wrong_tool", "missing_execution", "duplicate_execution", "boolean_exit"],
)
def test_scanner_run_tool_and_execution_set_are_exact(
    monkeypatch, measured: EvidenceFixture, poison: str
) -> None:
    fixture = measured.clone()

    def change(record):
        if poison == "wrong_attempt":
            record["run"]["GITHUB_RUN_ATTEMPT"] = "1"
        elif poison == "wrong_tool":
            record["tools"]["trivy"]["image"] = "trivy:latest"
        elif poison == "missing_execution":
            record["executions"].pop()
        elif poison == "duplicate_execution":
            record["executions"][-1] = record["executions"][0]
        else:
            record["executions"][0]["exit_code"] = False

    _receipt(fixture, change)
    _wire(monkeypatch, fixture)
    with pytest.raises(ValueError):
        importer.fetch_evidence(fixture.checkout.root, SELECTED)


@pytest.mark.parametrize(
    "name", ["tree-sbom.cdx.json", "gitleaks.json", "source-security-receipt.json"]
)
def test_missing_security_member_never_becomes_coverage_only_success(
    monkeypatch, measured: EvidenceFixture, name: str
) -> None:
    fixture = measured.clone()
    fixture.members[SECURITY.job].pop(name)
    fixture.repack(SECURITY)
    _wire(monkeypatch, fixture)
    with pytest.raises(ValueError, match="members"):
        importer.fetch_evidence(fixture.checkout.root, SELECTED)


@pytest.mark.parametrize("name", ["tree-sbom.cdx.json", "trivy.json"])
def test_stale_native_timestamp_cannot_be_rewrapped_in_fresh_security_receipt(
    monkeypatch, measured: EvidenceFixture, name: str
) -> None:
    fixture = measured.clone()
    report = json.loads(fixture.members[SECURITY.job][name])
    if name == "tree-sbom.cdx.json":
        report["metadata"]["timestamp"] = "2000-01-01T00:00:00Z"
    else:
        report["CreatedAt"] = "2000-01-01T00:00:00Z"
    _member(fixture, name, encoded(report))
    _wire(monkeypatch, fixture)
    with pytest.raises(ValueError, match="outside its admitted execution"):
        importer.fetch_evidence(fixture.checkout.root, SELECTED)


def test_consistent_hashes_cannot_launder_nonzero_scanner_findings(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = measured.clone()
    _member(fixture, "gitleaks.json", b'[{"RuleID":"neutral-negative-control"}]')
    _wire(monkeypatch, fixture)
    with pytest.raises(ValueError, match="Gitleaks"):
        importer.fetch_evidence(fixture.checkout.root, SELECTED)


def test_new_lock_bytes_in_caller_checkout_do_not_change_frozen_tool_identity(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = measured.clone()
    path = fixture.checkout.root / "apps/api/requirements.scanners.lock"
    original = path.read_bytes()
    swapped = original + b"# changed toolchain subject\n"
    _receipt(
        fixture, lambda record: record["tools"]["pip-audit"]["lock"].update(sha256=digest(swapped))
    )
    expected_tools = security_admission.expected_tools

    def swap_while_reading(root):
        if root != fixture.checkout.root:
            return expected_tools(root)
        path.write_bytes(swapped)
        try:
            return expected_tools(root)
        finally:
            path.write_bytes(original)

    monkeypatch.setattr(security_admission, "expected_tools", swap_while_reading)
    _wire(monkeypatch, fixture)
    with pytest.raises(ValueError, match="security tool identity mismatch"):
        importer.fetch_evidence(fixture.checkout.root, SELECTED)
    assert path.read_bytes() == original


def test_extra_artifact_uses_same_run_capture_and_stays_outside_native_index(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = measured.clone()
    producer = Producer("additional-proof", "proof-job", "Upload proof", ("proof.json",))
    fixture.add_artifact(producer, {"proof.json": b'{"neutral":"bytes"}'})
    _wire(monkeypatch, fixture)
    evidence, extras = importer.fetch_with_artifacts(fixture.checkout.root, SELECTED, (producer,))
    assert len(evidence.artifacts) == 3 and len(extras) == 1
    assert extras[0].members["proof.json"] == b'{"neutral":"bytes"}'
    assert len(fixture.api.downloads) == 8


def _package(fixture: EvidenceFixture) -> Producer:
    producer = package_producer(fixture.checkout)
    fixture.add_artifact(
        producer, {name: b"neutral captured package member" for name in producer.required_members}
    )
    return producer


def test_fixed_package_capture_uses_frozen_release_identity_and_exact_five_members(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = measured.clone()
    producer = _package(fixture)
    _wire(monkeypatch, fixture)
    evidence, (package,) = importer.fetch_with_artifacts(
        fixture.checkout.root, SELECTED, (PACKAGE,)
    )
    assert len(evidence.artifacts) == 3
    assert package.producer_job_name == PACKAGE.job
    assert set(package.members) == set(producer.required_members)
    assert (
        package.zip_bytes == fixture.api.responses[f"/actions/artifacts/{package.artifact_id}/zip"]
    )


@pytest.mark.parametrize("change", ["missing_zip", "foreign_release", "extra_member"])
def test_package_archive_cannot_replace_the_fixed_captured_release_census(
    monkeypatch, measured: EvidenceFixture, change: str
) -> None:
    fixture = measured.clone()
    producer = _package(fixture)
    members = fixture.members[PACKAGE.job]
    if change == "missing_zip":
        members.pop(producer.required_members[0])
    elif change == "foreign_release":
        members["dist/FOREIGN.zip"] = members.pop(producer.required_members[0])
    else:
        members["var/extra-pass.json"] = b'{"status":"PASS"}'
    fixture.repack(producer)
    _wire(monkeypatch, fixture)
    with pytest.raises(ValueError, match="members"):
        importer.fetch_with_artifacts(fixture.checkout.root, SELECTED, (PACKAGE,))


def test_package_filename_does_not_follow_a_changed_caller_release_file(
    measured: EvidenceFixture,
) -> None:
    fixture = measured.clone()
    expected = package_producer(fixture.checkout)
    path = fixture.checkout.root / "apps/api/src/korpus/release.json"
    original = path.read_bytes()
    path.write_bytes(b'{"distribution_artifact":"FOREIGN.zip"}')
    try:
        assert package_producer(fixture.checkout) == expected
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize(
    "payload", [b'{"tag":"v0.9.7","tag":"v0.9.8"}', b'{"distribution_artifact":"../foreign.zip"}']
)
def test_captured_release_identity_requires_strict_consistent_json(
    measured: EvidenceFixture, payload: bytes
) -> None:
    checkout = measured.checkout
    files = tuple(
        (path, mode, payload if path.as_posix().endswith("/release.json") else content)
        for path, mode, content in checkout.files
    )
    with pytest.raises(ValueError):
        package_producer(dataclasses.replace(checkout, files=files))


def test_final_source_change_revokes_otherwise_valid_capture(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = measured.clone()
    _wire(monkeypatch, fixture)
    captures = iter((fixture.checkout, dataclasses.replace(fixture.checkout, commit="f" * 40)))
    monkeypatch.setattr(importer, "capture_checkout", lambda root: next(captures))
    with pytest.raises(ValueError, match="source changed during"):
        importer.fetch_evidence(fixture.checkout.root, SELECTED)
