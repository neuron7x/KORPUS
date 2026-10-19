from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from korpus.application import github_assurance_receipts as receipts
from korpus.application import release_claim_git_tree as git_tree
from korpus.application import release_claim_hosted as hosted
from korpus.application import release_claim_sigstore as sigstore
from korpus.application import release_claim_tree as claim_tree
from korpus.application import release_coverage_projection as coverage_projection


def test_git_directory_rejects_missing_symlink_and_malformed_markers(tmp_path: Path) -> None:
    assert git_tree._git_directory(tmp_path) is None

    target = tmp_path / "target"
    target.mkdir()
    marker = tmp_path / ".git"
    marker.symlink_to(target, target_is_directory=True)
    assert git_tree._git_directory(tmp_path) is None

    marker.unlink()
    marker.write_text("not a gitfile\n", encoding="utf-8")
    assert git_tree._git_directory(tmp_path) is None

    marker.write_text("gitdir: missing\n", encoding="utf-8")
    assert git_tree._git_directory(tmp_path) is None

    marker.write_text("gitdir: target\n", encoding="utf-8")
    assert git_tree._git_directory(tmp_path) == target


def test_git_directory_rejects_unreadable_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / ".git"
    marker.write_text("gitdir: target\n", encoding="utf-8")

    def unreadable(_path: Path, *args: object, **kwargs: object) -> str:
        raise OSError("unreadable")

    monkeypatch.setattr(Path, "read_text", unreadable)
    assert git_tree._git_directory(tmp_path) is None


def test_git_command_requires_both_trusted_binary_and_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git_tree, "git_executable", lambda: None)
    assert git_tree._command(tmp_path, "status") is None

    monkeypatch.setattr(git_tree, "git_executable", lambda: "/usr/bin/git")
    monkeypatch.setattr(git_tree, "_git_directory", lambda _root: None)
    assert git_tree._command(tmp_path, "status") is None

    directory = tmp_path / "objects"
    directory.mkdir()
    monkeypatch.setattr(git_tree, "_git_directory", lambda _root: directory)
    command, environment = git_tree._command(tmp_path, "status") or ([], {})
    assert command[-1] == "status"
    assert command[0] == "/usr/bin/git"
    assert "GIT_DIR" not in environment


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (b"a" * 40 + b" blob 3\nabc\n", [b"abc"]),
        (b"wrong blob 3\nabc\n", None),
        (b"a" * 40 + b" tree 3\nabc\n", None),
        (b"a" * 40 + b" blob 4\nabc\n", None),
        (b"a" * 40 + b" blob 3\nabcX", None),
        (b"a" * 40 + b" blob 3\nabc\ntrailing", None),
        (b"\xff\n", None),
    ],
)
def test_blob_batch_parser_is_exact(
    output: bytes,
    expected: list[bytes] | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_id = "a" * 40
    monkeypatch.setattr(git_tree, "_command", lambda *_args: (["git"], {}))
    monkeypatch.setattr(
        git_tree.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=output),
    )
    assert git_tree._blob_bytes(tmp_path, [object_id]) == expected


def test_blob_reader_rejects_missing_invocation_and_process_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git_tree, "_command", lambda *_args: None)
    assert git_tree._blob_bytes(tmp_path, ["a" * 40]) is None

    monkeypatch.setattr(git_tree, "_command", lambda *_args: (["git"], {}))

    def failed(*_args: object, **_kwargs: object) -> Any:
        raise subprocess.CalledProcessError(1, ["git"])

    monkeypatch.setattr(git_tree.subprocess, "run", failed)
    assert git_tree._blob_bytes(tmp_path, ["a" * 40]) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"100644 blob abc",
        b"100644 blob\tname.py",
        b"100644 tree abc\tname.py",
        b"100644 blob abc\t/name.py",
        b"100644 blob abc\t../name.py",
        b"\xff blob abc\tname.py",
        b"100644 blob abc\t\xff",
    ],
)
def test_git_tree_record_rejects_malformed_entries(raw: bytes) -> None:
    assert git_tree._record(raw) is None


def test_git_tree_record_normalizes_regular_modes() -> None:
    assert git_tree._record(b"100644 blob abc\tname.py") == (Path("name.py"), "0644", "abc")
    assert git_tree._record(b"100755 blob def\ttool") == (Path("tool"), "0755", "def")
    assert git_tree._record(b"120000 blob ghi\tlink") == (Path("link"), "120000", "ghi")


def test_working_file_covers_regular_executable_symlink_and_non_file(tmp_path: Path) -> None:
    regular = tmp_path / "regular"
    regular.write_bytes(b"payload")
    assert git_tree._working_file(regular) == ("0644", b"payload")
    regular.chmod(0o755)
    assert git_tree._working_file(regular) == ("0755", b"payload")

    link = tmp_path / "link"
    link.symlink_to("regular")
    assert git_tree._working_file(link) == ("120000", b"regular")
    assert git_tree._working_file(tmp_path) is None
    assert git_tree._working_file(tmp_path / "absent") is None


def test_working_paths_refuses_walk_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_walk(_path: Path, _pattern: str) -> Any:
        raise OSError("walk failed")

    monkeypatch.setattr(Path, "rglob", broken_walk)
    assert git_tree._working_paths(tmp_path) is None


def test_tree_records_reject_invalid_empty_duplicate_or_excluded_entries() -> None:
    valid = b"100644 blob abc\tname.py"
    assert git_tree._tree_records(valid + b"\0") == [(Path("name.py"), "0644", "abc")]
    assert git_tree._tree_records(b"\xff\0") is None
    assert git_tree._tree_records(b"") is None
    assert git_tree._tree_records(valid + b"\0" + valid + b"\0") is None
    assert git_tree._tree_records(b"100644 blob abc\treports/result.json\0") is None


def test_git_files_refuses_each_failed_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git_tree, "_command", lambda *_args: None)
    assert git_tree.git_files(tmp_path) is None

    monkeypatch.setattr(git_tree, "_command", lambda *_args: (["git"], {}))

    def failed(*_args: object, **_kwargs: object) -> Any:
        raise subprocess.CalledProcessError(1, ["git"])

    monkeypatch.setattr(git_tree.subprocess, "run", failed)
    assert git_tree.git_files(tmp_path) is None

    monkeypatch.setattr(
        git_tree.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=b"invalid\0"),
    )
    assert git_tree.git_files(tmp_path) is None

    listing = b"100644 blob abc\tname.py\0"
    monkeypatch.setattr(
        git_tree.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=listing),
    )
    monkeypatch.setattr(git_tree, "_blob_bytes", lambda *_args: None)
    assert git_tree.git_files(tmp_path) is None

    monkeypatch.setattr(git_tree, "_blob_bytes", lambda *_args: [b"payload"])
    monkeypatch.setattr(git_tree, "_worktree_matches", lambda *_args: False)
    assert git_tree.git_files(tmp_path) is None

    monkeypatch.setattr(git_tree, "_worktree_matches", lambda *_args: True)
    assert git_tree.git_files(tmp_path) == [(Path("name.py"), "0644", b"payload")]


def _manifest_record(path: str, payload: bytes, *, mode: str = "0644") -> dict[str, object]:
    return {
        "path": path,
        "sha256": receipts.sha256_bytes(payload),
        "bytes": len(payload),
        "mode": mode,
    }


def test_manifest_record_rejects_invalid_paths_metadata_and_files(tmp_path: Path) -> None:
    assert claim_tree._manifest_record((tmp_path, None)) is None
    assert claim_tree._manifest_record((tmp_path, {})) is None
    for path in ("/absolute.py", "../escape.py", "reports/excluded.json"):
        assert claim_tree._manifest_record((tmp_path, {"path": path})) is None
    assert claim_tree._manifest_record((tmp_path, {"path": "absent.py"})) is None

    payload = b"value = 1\n"
    (tmp_path / "source.py").write_bytes(payload)
    (tmp_path / "source.py").chmod(0o644)
    valid = _manifest_record("source.py", payload)
    assert claim_tree._manifest_record((tmp_path, valid)) == (
        Path("source.py"),
        "0644",
        payload,
    )
    for field, poison in (("sha256", "0" * 64), ("bytes", 0), ("mode", "0755")):
        invalid = {**valid, field: poison}
        assert claim_tree._manifest_record((tmp_path, invalid)) is None


def test_manifest_files_fail_closed_and_accept_exact_unique_records(tmp_path: Path) -> None:
    manifest = tmp_path / "SOURCE_MANIFEST.json"
    assert claim_tree._manifest_files(tmp_path) is None
    manifest.write_text("{", encoding="utf-8")
    assert claim_tree._manifest_files(tmp_path) is None
    malformed_payloads: tuple[object, ...] = ([], {"files": "invalid"}, {"files": [None]})
    for payload in malformed_payloads:
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        assert claim_tree._manifest_files(tmp_path) is None

    content = b"answer = 42\n"
    (tmp_path / "source.py").write_bytes(content)
    (tmp_path / "source.py").chmod(0o644)
    record = _manifest_record("source.py", content)
    manifest.write_text(json.dumps({"files": [{**record, "sha256": "0" * 64}]}), encoding="utf-8")
    assert claim_tree._manifest_files(tmp_path) is None

    manifest.write_text(json.dumps({"files": [record, record]}), encoding="utf-8")
    assert claim_tree._manifest_files(tmp_path) is None

    manifest.write_text(json.dumps({"files": [record]}), encoding="utf-8")
    assert claim_tree._manifest_files(tmp_path) == [(Path("source.py"), "0644", content)]
    assert claim_tree.tracked_tree_digest(tmp_path) == claim_tree._digest(
        [(Path("source.py"), "0644", content)]
    )


def _write_verifier_configuration(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, os.stat_result]:
    executable = root / "gh"
    executable.write_bytes(b"trusted gh")
    executable.chmod(0o755)
    metadata = executable.stat()
    monkeypatch.setattr(sigstore, "VERIFIER_PATH", str(executable))
    monkeypatch.setattr(sigstore, "VERIFIER_VERSION", "1.2.3")
    monkeypatch.setattr(sigstore, "VERIFIER_SHA256", receipts.sha256_bytes(executable.read_bytes()))
    config = root / sigstore.VERIFIER_CONFIG_PATH
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "schema": "korpus.sigstore-verifier.v1",
                "path": str(executable),
                "version": "1.2.3",
                "sha256": sigstore.VERIFIER_SHA256,
            }
        ),
        encoding="utf-8",
    )
    return executable, metadata


def test_sigstore_verifier_configuration_and_file_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert sigstore.verifier_executable(tmp_path) == (
        None,
        "SIGSTORE_VERIFIER_CONFIG_INVALID",
    )
    executable, metadata = _write_verifier_configuration(tmp_path, monkeypatch)
    config = tmp_path / sigstore.VERIFIER_CONFIG_PATH
    config.write_text("{}", encoding="utf-8")
    assert sigstore.verifier_executable(tmp_path)[1] == "SIGSTORE_VERIFIER_CONFIG_INVALID"
    config.unlink()
    _write_verifier_configuration(tmp_path, monkeypatch)

    monkeypatch.setattr(sigstore.os, "lstat", lambda _path: (_ for _ in ()).throw(OSError()))
    assert sigstore.verifier_executable(tmp_path)[1] == "SIGSTORE_VERIFIER_NOT_REGULAR"

    monkeypatch.setattr(
        sigstore.os,
        "lstat",
        lambda _path: SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0),
    )
    assert sigstore.verifier_executable(tmp_path)[1] == "SIGSTORE_VERIFIER_NOT_REGULAR"

    monkeypatch.setattr(
        sigstore.os,
        "lstat",
        lambda _path: SimpleNamespace(st_mode=metadata.st_mode, st_uid=1000),
    )
    assert sigstore.verifier_executable(tmp_path)[1] == "SIGSTORE_VERIFIER_NOT_ROOT_OWNED"

    monkeypatch.setattr(
        sigstore.os,
        "lstat",
        lambda _path: SimpleNamespace(st_mode=metadata.st_mode | 0o022, st_uid=0),
    )
    assert sigstore.verifier_executable(tmp_path)[1] == "SIGSTORE_VERIFIER_MUTABLE"

    monkeypatch.setattr(
        sigstore.os,
        "lstat",
        lambda _path: SimpleNamespace(st_mode=metadata.st_mode, st_uid=0),
    )
    monkeypatch.setattr(sigstore, "sha256_bytes", lambda _payload: "0" * 64)
    assert sigstore.verifier_executable(tmp_path)[1] == "SIGSTORE_VERIFIER_DIGEST_MISMATCH"

    monkeypatch.setattr(sigstore, "sha256_bytes", receipts.sha256_bytes)
    original_read = Path.read_bytes

    def unreadable(path: Path) -> bytes:
        if path == executable:
            raise OSError("unreadable")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    assert sigstore.verifier_executable(tmp_path)[1] == "SIGSTORE_VERIFIER_UNREADABLE"


def test_sigstore_verifier_version_guards_and_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable, metadata = _write_verifier_configuration(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sigstore.os,
        "lstat",
        lambda _path: SimpleNamespace(st_mode=metadata.st_mode, st_uid=0),
    )

    def unavailable(*_args: object, **_kwargs: object) -> Any:
        raise subprocess.TimeoutExpired([str(executable)], 10)

    monkeypatch.setattr(sigstore.subprocess, "run", unavailable)
    assert sigstore.verifier_executable(tmp_path)[1] == "SIGSTORE_VERIFIER_VERSION_UNAVAILABLE"

    for result in (
        SimpleNamespace(returncode=1, stdout="gh version 1.2.3\n"),
        SimpleNamespace(returncode=0, stdout=""),
        SimpleNamespace(returncode=0, stdout="gh version 9.9.9\n"),
    ):
        monkeypatch.setattr(
            sigstore.subprocess,
            "run",
            lambda *_args, _result=result, **_kwargs: _result,
        )
        assert sigstore.verifier_executable(tmp_path)[1] == "SIGSTORE_VERIFIER_VERSION_MISMATCH"

    monkeypatch.setattr(
        sigstore.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="gh version 1.2.3 linux\n"),
    )
    assert sigstore.verifier_executable(tmp_path) == (str(executable), None)


def test_sigstore_bundle_refuses_invalid_inputs_and_process_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sigstore, "verifier_executable", lambda _root: ("gh", None))
    assert not sigstore.verify_sigstore_bundle(
        tmp_path, "attestation.json", "bundle.json", "a" * 40, hosted.SOURCE_REF
    )

    trusted_root = tmp_path / hosted.TRUSTED_ROOT_PATH
    trusted_root.parent.mkdir(parents=True)
    trusted_root.write_bytes(b"trusted root")
    monkeypatch.setattr(sigstore, "TRUSTED_ROOT_SHA256", receipts.sha256_bytes(b"trusted root"))
    assert not sigstore.verify_sigstore_bundle(
        tmp_path, "attestation.json", "bundle.json", "invalid", hosted.SOURCE_REF
    )
    assert not sigstore.verify_sigstore_bundle(
        tmp_path, "attestation.json", "bundle.json", "a" * 40, "refs/heads/foreign"
    )

    def unavailable(*_args: object, **_kwargs: object) -> Any:
        raise subprocess.TimeoutExpired(["gh"], 90)

    monkeypatch.setattr(sigstore.subprocess, "run", unavailable)
    assert not sigstore.verify_sigstore_bundle(
        tmp_path, "attestation.json", "bundle.json", "a" * 40, hosted.SOURCE_REF
    )

    for result, expected in (
        (SimpleNamespace(returncode=1, stdout="[]"), False),
        (SimpleNamespace(returncode=0, stdout="not json"), False),
        (SimpleNamespace(returncode=0, stdout="[]"), False),
        (SimpleNamespace(returncode=0, stdout="[{}, {}]"), False),
        (SimpleNamespace(returncode=0, stdout="[null]"), False),
        (SimpleNamespace(returncode=0, stdout='[{"verificationResult": {}}]'), False),
        (
            SimpleNamespace(
                returncode=0,
                stdout='[{"verificationResult": {"verifiedTimestamps": ["rekor"]}}]',
            ),
            True,
        ),
    ):
        monkeypatch.setattr(
            sigstore.subprocess,
            "run",
            lambda *_args, _result=result, **_kwargs: _result,
        )
        assert (
            sigstore.verify_sigstore_bundle(
                tmp_path, "attestation.json", "bundle.json", "a" * 40, hosted.SOURCE_REF
            )
            is expected
        )


def test_sigstore_receipt_wrapper_requires_typed_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[tuple[str, str]] = []

    def verify(_root: Path, _attestation: str, _bundle: str, commit: str, source_ref: str) -> bool:
        observed.append((commit, source_ref))
        return True

    monkeypatch.setattr(sigstore, "verify_sigstore_bundle", verify)
    assert not sigstore.sigstore_verified(tmp_path, "a", "b", {}, hosted.SOURCE_REF)
    assert not sigstore.sigstore_verified(tmp_path, "a", "b", {"commit_sha": "a" * 40}, object())
    assert sigstore.sigstore_verified(
        tmp_path, "a", "b", {"commit_sha": "a" * 40}, hosted.SOURCE_REF
    )
    assert observed == [("a" * 40, hosted.SOURCE_REF)]


def _executions(paths: list[str]) -> dict[str, dict[str, object]]:
    return {
        claim_id: {
            "executor": executor,
            "exit_code": 0,
            "result": {"count": 1},
            "artifacts": paths,
        }
        for claim_id, executor in hosted.CLAIM_EXECUTORS.items()
    }


def test_hosted_paths_records_and_attestation_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hosted.hosted_paths("v1")[0].endswith("/RELEASE_CLAIM_ATTESTATION.json")
    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(b"{}")
    assert hosted._records(tmp_path, []) is None
    assert hosted._records(tmp_path, ["artifact.json", "artifact.json"]) is None
    assert hosted._records(tmp_path, ["absent.json"]) is None
    assert hosted._records(tmp_path, ["artifact.json"]) == {
        "artifact.json": {"sha256": receipts.sha256_bytes(b"{}"), "bytes": 2}
    }

    monkeypatch.setattr(hosted, "tracked_tree_digest", lambda _root: "b" * 64)
    executions = _executions(["artifact.json"])
    with pytest.raises(ValueError, match="identity"):
        hosted.new_attestation(tmp_path, "v1", "invalid", executions)
    with pytest.raises(ValueError, match="identity"):
        hosted.new_attestation(
            tmp_path, "v1", "a" * 64, executions, source_ref="refs/heads/foreign"
        )
    with pytest.raises(ValueError, match="identity"):
        hosted.new_attestation(tmp_path, "v1", "a" * 64, {})

    wrong_executor = _executions(["artifact.json"])
    wrong_executor["CLM-WEB"]["executor"] = "backend"
    with pytest.raises(ValueError, match="did not pass"):
        hosted.new_attestation(tmp_path, "v1", "a" * 64, wrong_executor)

    incomplete = _executions(["artifact.json"])
    incomplete["CLM-WEB"]["artifacts"] = "artifact.json"
    with pytest.raises(ValueError, match="incomplete"):
        hosted.new_attestation(tmp_path, "v1", "a" * 64, incomplete)

    attestation = hosted.new_attestation(tmp_path, "v1", "a" * 64, executions)
    assert hosted.attestation_identity(attestation, "v1", "a" * 64, "b" * 64)
    assert not hosted.attestation_identity(
        {**attestation, "status": "FAIL"}, "v1", "a" * 64, "b" * 64
    )


def test_hosted_entry_shape_and_receipt_subject() -> None:
    record = {"sha256": "a" * 64, "bytes": 0}
    entry = {
        "status": "PASS",
        "executor": hosted.CLAIM_EXECUTORS["CLM-WEB"],
        "exit_code": 0,
        "result": {},
        "artifacts": {"evidence.json": record},
    }
    assert not hosted._entry_shape("CLM-WEB", None)
    assert hosted._entry_shape("CLM-WEB", entry)
    assert not hosted._entry_shape(
        "CLM-WEB", {**entry, "artifacts": {"evidence.json": {**record, "bytes": True}}}
    )
    assert hosted.receipt_subject("v1", "a" * 64, "b" * 64, hosted.SOURCE_REF) == {
        "release-claims": {
            "release": "v1",
            "source_tree_sha256": "a" * 64,
            "digest_scope": "evidence_paths",
            "tracked_tree_sha256": "b" * 64,
            "source_ref": hosted.SOURCE_REF,
            "claims": sorted(hosted.CLAIM_EXECUTORS),
        }
    }


def _canonical_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": receipts.CANONICAL_REPOSITORY,
        "GITHUB_REPOSITORY_ID": str(receipts.CANONICAL_REPOSITORY_ID),
        "GITHUB_REPOSITORY_OWNER_ID": str(receipts.CANONICAL_OWNER_ID),
        "KORPUS_GITHUB_WORKFLOW_ID": str(receipts.CANONICAL_WORKFLOW_ID),
        "GITHUB_WORKFLOW_REF": (
            f"{receipts.CANONICAL_REPOSITORY}/{receipts.CANONICAL_WORKFLOW_PATH}@refs/heads/main"
        ),
        "GITHUB_RUN_ID": "42",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_SHA": "a" * 40,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_github_identity_environment_and_api_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _canonical_environment(monkeypatch)
    identity = receipts.identity_from_environment()
    assert receipts.canonical_identity(identity)

    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    with pytest.raises(ValueError, match="canonical GitHub"):
        receipts.identity_from_environment()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_RUN_ID", "not-an-int")
    with pytest.raises(ValueError, match="canonical GitHub"):
        receipts.identity_from_environment()

    assert receipts.identity_from_run({}) == {
        "repository": None,
        "repository_id": None,
        "repository_owner_id": None,
        "workflow_id": None,
        "workflow_path": None,
        "run_id": None,
        "run_attempt": None,
        "commit_sha": None,
    }
    normalized = receipts.identity_from_run(
        {
            "repository": {
                "full_name": receipts.CANONICAL_REPOSITORY,
                "id": receipts.CANONICAL_REPOSITORY_ID,
                "owner": {"id": receipts.CANONICAL_OWNER_ID},
            },
            "workflow_id": receipts.CANONICAL_WORKFLOW_ID,
            "path": receipts.CANONICAL_WORKFLOW_PATH,
            "id": 42,
            "run_attempt": 2,
            "head_sha": "a" * 40,
        }
    )
    assert receipts.canonical_identity(normalized)


def test_github_receipt_constructors_reject_noncanonical_identity() -> None:
    with pytest.raises(ValueError, match="invalid canonical"):
        receipts.new_receipt(
            {},
            kind="coverage",
            job="coverage",
            source_tree_sha256="a" * 64,
            artifacts={},
            subjects={},
        )
    with pytest.raises(ValueError, match="non-canonical"):
        receipts.admission_payload({}, {})
    assert receipts._environment_int("VARIABLE_THAT_DOES_NOT_EXIST") is None


def _write_coverage_bundle(root: Path, values: dict[str, object]) -> None:
    directory = root / "var/ci-evidence"
    directory.mkdir(parents=True, exist_ok=True)
    names = {
        "union": "coverage-union.json",
        "plan": "coverage-gap-plan.json",
        "receipt": "coverage-ci-receipt.json",
        "admission": "assurance-admission.json",
    }
    for key, name in names.items():
        (directory / name).write_text(json.dumps(values[key]), encoding="utf-8")


def test_load_coverage_bundle_rejects_absent_invalid_and_nonobject_payloads(
    tmp_path: Path,
) -> None:
    assert coverage_projection.load_coverage_bundle(tmp_path) is None
    values: dict[str, object] = {
        "union": {},
        "plan": {},
        "receipt": {},
        "admission": {},
    }
    _write_coverage_bundle(tmp_path, values)
    bundle = coverage_projection.load_coverage_bundle(tmp_path)
    assert bundle is not None and bundle.union == {}

    target = tmp_path / "var/ci-evidence/coverage-union.json"
    target.write_text("{", encoding="utf-8")
    assert coverage_projection.load_coverage_bundle(tmp_path) is None
    target.write_text("[]", encoding="utf-8")
    assert coverage_projection.load_coverage_bundle(tmp_path) is None


def test_project_coverage_requires_binding_and_nonzero_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert coverage_projection.project_coverage(tmp_path, "a" * 64, "v1", "b" * 64) is None

    bundle = coverage_projection.CoverageBundle(
        union={"totals": {"num_statements": 0, "num_branches": 1}},
        plan={},
        receipt={"run_id": 42, "run_attempt": 2},
        admission={},
        raw={"receipt": b"receipt"},
    )
    monkeypatch.setattr(coverage_projection, "load_coverage_bundle", lambda _root: bundle)
    monkeypatch.setattr(
        coverage_projection, "coverage_binding_problem", lambda *_args, **_kwargs: "invalid"
    )
    assert coverage_projection.project_coverage(tmp_path, "a" * 64, "v1", "b" * 64) is None

    monkeypatch.setattr(
        coverage_projection, "coverage_binding_problem", lambda *_args, **_kwargs: None
    )
    assert coverage_projection.project_coverage(tmp_path, "a" * 64, "v1", "b" * 64) is None

    bundle.union["totals"] = {
        "num_statements": 4,
        "covered_lines": 3,
        "num_branches": 2,
        "covered_branches": 1,
    }
    assert coverage_projection.project_coverage(tmp_path, "a" * 64, "v1", "b" * 64) == {
        "schema": "korpus.coverage-report.v2",
        "status": "PASS",
        "release": "v1",
        "source_tree_sha256": "a" * 64,
        "statement_coverage_percent": 75.0,
        "branch_coverage_percent": 50.0,
        "measured_from": "var/ci-evidence/coverage-union.json",
        "ci_receipt_sha256": receipts.sha256_bytes(b"receipt"),
        "github_run_id": 42,
        "github_run_attempt": 2,
    }
