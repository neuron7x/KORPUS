from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from korpus.application import release_claim_admission
from korpus.application.release_claim_admission import canonical_paths_admitted

from scripts.full_ssot_packager import _zip_tree, stage_full_ssot
from scripts.generate_manifest import write_manifest
from scripts.manifest_paths import distribution_manifest_contract, expected_full_ssot_receipt
from scripts.verify_package import verify

EVIDENCE = "reports/release/v9/evidence.json"
ROOT = Path(__file__).resolve().parents[3]


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _stage(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    release = {
        "schema": "korpus.release-identity.v1",
        "product": "KORPUS",
        "version": "9",
        "tag": "v9",
        "artifact_stem": "KORPUS_v9",
        "distribution_artifact": "KORPUS_v9.zip",
    }
    _write(source / "apps/api/src/korpus/release.json", release)
    _write(source / EVIDENCE, {"status": "PASS"})
    write_manifest(source, source / "SOURCE_MANIFEST.json", kind="source")
    stage = tmp_path / "KORPUS"
    stage.mkdir()
    stage_full_ssot(source, stage)
    return stage


def _archive(stage: Path, path: Path) -> Path:
    _zip_tree(stage, path)
    return path


def _receipt(stage: Path) -> dict[str, object]:
    return json.loads((stage / "FULL_SSOT_PACKAGE_RECEIPT.json").read_text(encoding="utf-8"))


def _repository(root: Path, signing_key: Path | None = None, *, source_marker: bool = True) -> None:
    if source_marker:
        (root / ".korpus-source-root").write_text(
            "korpus.canonical-source-root.v1\nrepository=neuron7x/KORPUS\npackage_included=false\n",
            encoding="utf-8",
        )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin", "git@github.com:neuron7x/KORPUS.git"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Claim Test"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "claim-test@example.invalid"],
        check=True,
    )
    command = ["git", "-C", str(root), "commit", "-qm", "fixture"]
    if signing_key is not None:
        subprocess.run(["git", "-C", str(root), "config", "gpg.format", "ssh"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.signingkey", str(signing_key)],
            check=True,
        )
        command.insert(4, "-S")
    else:
        command.insert(4, "--no-gpg-sign")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(command, check=True)


def _trust_test_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    key = tmp_path / "trusted-signing-key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    public = key.with_suffix(".pub").read_text(encoding="utf-8").strip()
    allowed = f"claim-test@example.invalid {public}\n".encode()
    monkeypatch.setattr(release_claim_admission, "TRUSTED_SIGNERS", allowed)
    return key


def test_full_ssot_receipt_exactly_binds_the_receipt_excluded_manifest(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path)
    manifest_path = stage / "DISTRIBUTION_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = _receipt(stage)
    paths = [record["path"] for record in manifest["files"]]

    assert "FULL_SSOT_PACKAGE_RECEIPT.json" not in paths
    assert receipt["status"] == "PASS"
    assert receipt["status_scope"] == "ARCHIVE_INTEGRITY_ONLY"
    assert receipt["provenance_status"] == "NOT_ADMITTED"
    assert receipt["failures"] == []
    assert (
        receipt["distribution_manifest_sha256"]
        == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )
    assert receipt["distribution_manifest_root_sha256"] == manifest["root_sha256"]
    assert receipt["distribution_records"] == manifest["file_count"]
    assert not canonical_paths_admitted(stage, [EVIDENCE])
    failures, count = verify(_archive(stage, tmp_path / "full.zip"), require_full_ssot=True)
    assert failures == []
    assert count == manifest["file_count"] + 2


def test_fail_receipt_cannot_authorize_gitless_release_evidence(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    receipt = _receipt(stage)
    receipt["status"] = "FAIL"
    receipt["failures"] = ["producer_failed"]
    _write(stage / "FULL_SSOT_PACKAGE_RECEIPT.json", receipt)

    assert not canonical_paths_admitted(stage, [EVIDENCE])
    failures, _ = verify(_archive(stage, tmp_path / "failed.zip"), require_full_ssot=True)
    assert "full SSOT receipt status is not PASS" in failures
    assert "full SSOT receipt contains failures" in failures


def test_reformatted_manifest_breaks_its_exact_receipt_binding(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    path = stage / "DISTRIBUTION_MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(manifest, separators=(",", ":")) + "\n", encoding="utf-8")

    assert not canonical_paths_admitted(stage, [EVIDENCE])
    failures, _ = verify(_archive(stage, tmp_path / "reformatted.zip"), require_full_ssot=True)
    assert any("distribution_manifest_sha256" in failure for failure in failures)


def test_rebuilt_manifest_cannot_reuse_a_receipt_for_older_payload(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    receipt_path = stage / "FULL_SSOT_PACKAGE_RECEIPT.json"
    original_receipt = receipt_path.read_bytes()
    _write(stage / EVIDENCE, {"status": "PASS", "tampered": True})
    receipt_path.unlink()
    write_manifest(stage, stage / "DISTRIBUTION_MANIFEST.json", kind="distribution")
    receipt_path.write_bytes(original_receipt)
    receipt_path.chmod(0o644)

    assert not canonical_paths_admitted(stage, [EVIDENCE])
    failures, _ = verify(_archive(stage, tmp_path / "rebuilt.zip"), require_full_ssot=True)
    assert any("distribution_manifest_sha256" in failure for failure in failures)


def test_self_asserted_receipt_fields_are_rejected_instead_of_trusted(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    receipt = _receipt(stage)
    receipt["canonical_authorized"] = True
    receipt["provenance_status"] = "ADMITTED"
    _write(stage / "FULL_SSOT_PACKAGE_RECEIPT.json", receipt)

    assert not canonical_paths_admitted(stage, [EVIDENCE])
    failures, _ = verify(_archive(stage, tmp_path / "self-authorized.zip"), require_full_ssot=True)
    assert "full SSOT receipt fields are not exact" in failures
    assert any("provenance_status" in failure for failure in failures)


def test_unmanifested_payload_cannot_expand_a_gitless_package(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    _write(stage / "reports/injected.json", {"status": "PASS"})

    assert not canonical_paths_admitted(stage, [EVIDENCE])
    failures, _ = verify(_archive(stage, tmp_path / "injected.zip"), require_full_ssot=True)
    assert any("reports/injected.json" in failure for failure in failures)


def test_full_ssot_mode_refuses_an_archive_without_a_receipt(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    (stage / "FULL_SSOT_PACKAGE_RECEIPT.json").unlink()
    failures, _ = verify(_archive(stage, tmp_path / "missing.zip"), require_full_ssot=True)
    assert "exact full SSOT package receipt v4 is required" in failures


def test_manifest_aggregate_fields_and_duplicate_paths_are_not_declarative(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path)
    manifest_path = stage / "DISTRIBUTION_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["kind"] = "forged"
    manifest["manifest_self_excluded"] = False
    manifest["file_count"] = -1
    manifest["root_sha256"] = "not-a-digest"
    manifest["files"].append(dict(manifest["files"][0]))
    _write(manifest_path, manifest)

    failures, _ = verify(_archive(stage, tmp_path / "forged.zip"), require_full_ssot=True)
    assert "invalid distribution manifest schema" in failures
    assert "invalid distribution manifest file count" in failures
    assert "invalid distribution manifest root digest" in failures
    assert any("duplicate distribution manifest paths" in failure for failure in failures)


def test_fully_rebuilt_self_consistent_gitless_forge_is_integrity_only(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path)
    _write(stage / EVIDENCE, {"status": "PASS", "forged": True})
    (stage / "FULL_SSOT_PACKAGE_RECEIPT.json").unlink()
    manifest = write_manifest(stage, stage / "DISTRIBUTION_MANIFEST.json", kind="distribution")
    receipt = expected_full_ssot_receipt(stage, manifest)
    assert receipt is not None
    receipt_path = stage / "FULL_SSOT_PACKAGE_RECEIPT.json"
    _write(receipt_path, receipt)
    receipt_path.chmod(0o644)
    archive = _archive(stage, tmp_path / "self-consistent-forge.zip")

    failures, _ = verify(archive, require_full_ssot=True)
    assert failures == []
    assert not canonical_paths_admitted(stage, [EVIDENCE])
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_package.py"), "--require-full-ssot", archive],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert output["verification_scope"] == "archive_integrity"
    assert output["provenance_admitted"] is False


def test_strict_verifier_rejects_any_nonrequested_payload_tamper(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path)
    _write(stage / "apps/api/src/korpus/release.json", {"tampered": True})

    failures, _ = verify(_archive(stage, tmp_path / "payload-tampered.zip"), require_full_ssot=True)

    assert "digest mismatch: apps/api/src/korpus/release.json" in failures


def test_strict_verifier_rejects_any_nonrequested_mode_tamper(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    evidence = stage / EVIDENCE
    expected = f"{evidence.stat().st_mode & 0o777:04o}"
    evidence.chmod(0o755)

    failures, _ = verify(_archive(stage, tmp_path / "mode-tampered.zip"), require_full_ssot=True)

    assert f"mode mismatch: {EVIDENCE} expected={expected} actual=0755" in failures


def test_distribution_regeneration_keeps_receipt_outside_the_manifest(tmp_path: Path) -> None:
    stage = _stage(tmp_path)

    manifest = write_manifest(stage, stage / "DISTRIBUTION_MANIFEST.json", kind="distribution")

    assert "FULL_SSOT_PACKAGE_RECEIPT.json" not in {record["path"] for record in manifest["files"]}


def test_strict_verifier_rejects_executable_distribution_manifest(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    (stage / "DISTRIBUTION_MANIFEST.json").chmod(0o755)

    failures, _ = verify(_archive(stage, tmp_path / "manifest-0755.zip"), require_full_ssot=True)

    assert "distribution manifest mode must be 0644" in failures


def test_release_claim_admission_imports_without_repository_scripts(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "apps/api/src")}
    completed = subprocess.run(
        [sys.executable, "-c", "import korpus.application.release_claim_admission"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_unsigned_local_git_cannot_mint_provenance(tmp_path: Path) -> None:
    root = tmp_path / "unsigned"
    _write(root / EVIDENCE, {"status": "PASS"})
    _repository(root)

    assert not canonical_paths_admitted(root, [EVIDENCE])


def test_external_trusted_signature_admits_an_indexed_git_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "signed"
    _write(root / EVIDENCE, {"status": "PASS"})
    key = _trust_test_key(tmp_path, monkeypatch)
    _repository(root, key)

    assert canonical_paths_admitted(root, [EVIDENCE])


def test_trusted_signed_head_does_not_admit_staged_forged_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "staged-forge"
    _write(root / EVIDENCE, {"status": "PASS"})
    key = _trust_test_key(tmp_path, monkeypatch)
    _repository(root, key)
    _write(root / EVIDENCE, {"status": "PASS", "forged": True})
    subprocess.run(["git", "-C", str(root), "add", EVIDENCE], check=True)

    assert not canonical_paths_admitted(root, [EVIDENCE])


@pytest.mark.parametrize("relative", ["reports/invalid\x00.json", "reports/invalid\ud800.json"])
def test_malformed_git_path_arguments_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    root = tmp_path / "signed"
    _write(root / EVIDENCE, {"status": "PASS"})
    key = _trust_test_key(tmp_path, monkeypatch)
    _repository(root, key)

    assert not canonical_paths_admitted(root, [relative])


@pytest.mark.parametrize(
    "relative",
    [
        "vendor/.git./config",
        "vendor/.git /config",
        "vendor/.gitmodules.",
        "vendor/.git::$DATA/config",
        "vendor/.git:x/config",
        "vendor/git~1/config",
        "vendor/.gitmodules::$DATA",
        "vendor/GITMOD~1",
        "vendor/.g\u200cit/config",
        "vendor/.gitmod\u200cules",
    ],
)
def test_signed_head_does_not_admit_windows_git_metadata_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    root = tmp_path / "git-alias"
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    (root / relative).write_text("metadata\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "core.protectNTFS", "false"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "core.protectHFS", "false"], check=True)
    key = _trust_test_key(tmp_path, monkeypatch)
    _repository(root, key)

    assert not canonical_paths_admitted(root, [relative])


def test_full_ssot_tree_stays_unadmitted_with_embedded_trusted_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = _stage(tmp_path)
    key = _trust_test_key(tmp_path, monkeypatch)
    _repository(stage, key, source_marker=False)

    assert not canonical_paths_admitted(stage, [EVIDENCE])


@pytest.mark.parametrize("marker_mutation", ["intact", "remove_receipt", "remove_both"])
def test_legacy_full_ssot_root_markers_refuse_embedded_trusted_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marker_mutation: str
) -> None:
    root = tmp_path / "legacy-package"
    _write(root / EVIDENCE, {"status": "PASS"})
    _write(
        root / "FULL_SSOT_PACKAGE_RECEIPT.json",
        {
            "schema": "korpus.full-ssot-package-receipt.v2",
            "package_role": "FULL_SSOT_CANONICAL",
        },
    )
    _write(
        root / "DISTRIBUTION_MANIFEST.json",
        {
            "schema": "korpus.distribution-manifest.v2",
            "kind": "distribution",
            "files": [{"path": "FULL_SSOT_PACKAGE_RECEIPT.json"}],
        },
    )
    key = _trust_test_key(tmp_path, monkeypatch)
    _repository(root, key, source_marker=False)
    if marker_mutation in {"remove_receipt", "remove_both"}:
        (root / "FULL_SSOT_PACKAGE_RECEIPT.json").unlink()
    if marker_mutation == "remove_both":
        (root / "DISTRIBUTION_MANIFEST.json").unlink()

    assert not canonical_paths_admitted(root, [EVIDENCE])


@pytest.mark.parametrize("receipt_mutation", ["delete", "invalid"])
def test_restored_package_marker_tamper_cannot_unlock_embedded_trusted_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receipt_mutation: str
) -> None:
    stage = _stage(tmp_path)
    key = _trust_test_key(tmp_path, monkeypatch)
    _repository(stage, key, source_marker=False)
    receipt = stage / "FULL_SSOT_PACKAGE_RECEIPT.json"
    if receipt_mutation == "delete":
        receipt.unlink()
    else:
        receipt.write_text("not JSON\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(stage), "add", "-A"], check=True)

    assert not canonical_paths_admitted(stage, [EVIDENCE])


def test_restored_package_cannot_borrow_a_trusted_source_git_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = tmp_path / "trusted-source"
    _write(trusted / EVIDENCE, {"status": "PASS"})
    key = _trust_test_key(tmp_path, monkeypatch)
    _repository(trusted, key)
    stage = _stage(tmp_path / "package")
    shutil.copytree(trusted / ".git", stage / ".git")
    (stage / "FULL_SSOT_PACKAGE_RECEIPT.json").unlink()
    (stage / "DISTRIBUTION_MANIFEST.json").unlink()

    assert not (stage / ".korpus-source-root").exists()
    assert not canonical_paths_admitted(stage, [EVIDENCE])


@pytest.mark.parametrize(
    "forbidden",
    [
        ".git/config",
        "vendor/.GIT/HEAD",
        ".gitmodules",
        ".git./config",
        ".git /config",
        ".gitmodules.",
        ".git::$DATA/config",
        ".git:x/config",
        "git~1/config",
        ".gitmodules::$DATA",
        "GITMOD~1",
        ".g\u200cit/config",
        ".gitmod\u200cules",
    ],
)
def test_distribution_manifest_contract_rejects_git_metadata_records(
    tmp_path: Path, forbidden: str
) -> None:
    stage = _stage(tmp_path)
    manifest_path = stage / "DISTRIBUTION_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = forbidden
    _write(manifest_path, manifest)

    _, _, failures = distribution_manifest_contract(stage)

    assert "invalid distribution manifest record shape" in failures
