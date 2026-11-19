"""The final ZIP binds its inner source and research claims to its own bytes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.manifest_lib.integrity import manifest_root
from scripts.verify_package import verify

from .package_fixtures import (
    RELEASE,
    RESEARCH,
    SNAPSHOT,
    SOURCE,
    encoded,
    package_files,
    resnapshot,
    write_package,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("prefix", ["", "KORPUS/"])
@pytest.mark.parametrize("mode", [0o644, 0o755, 0o750])
def test_complete_package_preserves_source_and_executable_modes(
    tmp_path: Path, prefix: str, mode: int
) -> None:
    modes = {"scripts/example.sh": mode}
    files = package_files({"scripts/example.sh": b"#!/bin/sh\nexit 0\n"}, modes=modes)
    archive = tmp_path / "complete.zip"
    count = write_package(archive, files, prefix=prefix, modes=modes)
    assert verify(archive) == ([], count)


@pytest.mark.parametrize(
    "poison", ["missing", "hash", "bytes", "mode", "omitted", "path", "duplicate"]
)
def test_coherent_distribution_cannot_hide_a_forged_source_manifest(
    tmp_path: Path, poison: str
) -> None:
    files = package_files()
    source = json.loads(files[SOURCE])
    records = source["files"]
    if poison in {"hash", "bytes", "mode", "path"}:
        field, value = {
            "hash": ("sha256", "0" * 64),
            "bytes": ("bytes", 999),
            "mode": ("mode", "0755"),
            "path": ("path", "apps/api/src/absent.py"),
        }[poison]
        records[0][field] = value
    elif poison == "omitted":
        records.pop()
    elif poison == "duplicate":
        records.append(records[0])
    source.update(file_count=len(records), root_sha256=manifest_root(records))
    files[SOURCE] = encoded(source)
    if poison == "missing":
        del files[SOURCE]
    archive = tmp_path / "forged-source.zip"
    write_package(archive, files)
    failures, _ = verify(archive)
    assert failures, f"forged source manifest admitted: {poison}"
    assert any("source" in failure.lower() for failure in failures)


@pytest.mark.parametrize("field", ["source_tree_sha256", "evidence_source_sha256", "status"])
def test_foreign_research_claims_fail_even_after_a_coherent_resnapshot(
    tmp_path: Path, field: str
) -> None:
    files = package_files()
    report = json.loads(files[RESEARCH])
    report[field] = "FAIL" if field == "status" else "f" * 64
    files[RESEARCH] = encoded(report)
    resnapshot(files)
    archive = tmp_path / "foreign-report.zip"
    write_package(archive, files)
    failures, _ = verify(archive)
    assert failures, f"foreign {field} accepted with its recomputed snapshot"


@pytest.mark.parametrize("missing", [RESEARCH, SNAPSHOT, "reports/EVAL_REPORT.json"])
def test_missing_canonical_research_member_is_rejected(tmp_path: Path, missing: str) -> None:
    files = package_files()
    del files[missing]
    archive = tmp_path / "missing-report.zip"
    write_package(archive, files)
    assert verify(archive)[0], f"missing canonical member accepted: {missing}"


def test_changed_canonical_report_with_rebuilt_distribution_is_rejected(tmp_path: Path) -> None:
    files = package_files()
    files["reports/EVAL_REPORT.json"] = b'{"changed":true}\n'
    archive = tmp_path / "stale-snapshot.zip"
    write_package(archive, files)
    assert verify(archive)[0]


def test_valid_inner_contracts_cannot_repair_failed_distribution_integrity(tmp_path: Path) -> None:
    archive = tmp_path / "invalid-outer.zip"
    write_package(archive, package_files())
    with zipfile.ZipFile(archive) as source:
        members = [(info, source.read(info)) for info in source.infolist()]
    with zipfile.ZipFile(archive, "w") as target:
        for info, body in members:
            candidate = body
            if info.filename.endswith("/DISTRIBUTION_MANIFEST.json"):
                distribution = json.loads(body)
                distribution["files"][0]["sha256"] = "0" * 64
                distribution["root_sha256"] = manifest_root(distribution["files"])
                candidate = encoded(distribution)
            target.writestr(info, candidate)
    failures, _ = verify(archive)
    assert any("digest mismatch" in failure for failure in failures)


@pytest.mark.parametrize(
    "poison",
    [
        "empty",
        "missing",
        "duplicate",
        "extra",
        "parent",
        "absolute",
        "schema",
        "release",
        "status",
        "limitations",
        "hash",
        "bytes",
        "bool_bytes",
    ],
)
def test_noncanonical_research_snapshot_is_rejected(tmp_path: Path, poison: str) -> None:
    files = package_files()
    snapshot = json.loads(files[SNAPSHOT])
    records = snapshot["records"]
    if poison == "empty":
        records.clear()
    elif poison == "missing":
        records.pop()
    elif poison == "duplicate":
        records.append(records[0])
    elif poison in {"extra", "parent", "absolute"}:
        name = {"extra": "reports/extra.json", "parent": "../outside", "absolute": "/outside"}[
            poison
        ]
        records.append({"path": name, "bytes": 0, "sha256": "0" * 64})
    elif poison in {"hash", "bytes", "bool_bytes"}:
        field, value = {
            "hash": ("sha256", "0" * 64),
            "bytes": ("bytes", 999),
            "bool_bytes": ("bytes", True),
        }[poison]
        records[0][field] = value
    else:
        snapshot[poison] = [] if poison == "limitations" else "foreign"
    files[SNAPSHOT] = encoded(snapshot)
    archive = tmp_path / "invalid-snapshot.zip"
    write_package(archive, files)
    assert verify(archive)[0], f"noncanonical snapshot accepted: {poison}"


@pytest.mark.parametrize("member", [SOURCE, RESEARCH, SNAPSHOT, RELEASE])
@pytest.mark.parametrize("poison", ["malformed", "duplicate_key", "nonfinite"])
def test_package_semantic_json_is_strict(tmp_path: Path, member: str, poison: str) -> None:
    files = package_files()
    original = files[member]
    if poison == "malformed":
        body = b"{"
    elif poison == "duplicate_key":
        payload = json.loads(original)
        key = next(iter(payload))
        body = original.replace(b"{", b"{" + json.dumps(key).encode() + b':"foreign",', 1)
    else:
        body = original.replace(b"{", b'{"not_finite":NaN,', 1)
    # Release bytes remain coherently represented by source/report manifests.
    if member == RELEASE:
        files = package_files({RELEASE: body})
    else:
        files[member] = body
        if member == RESEARCH and poison != "malformed":
            resnapshot(files)
    archive = tmp_path / "invalid-json.zip"
    write_package(archive, files)
    assert verify(archive)[0], f"{poison} JSON accepted: {member}"


def test_separately_governed_production_report_does_not_expand_research_set(
    tmp_path: Path,
) -> None:
    files = package_files({"reports/PRODUCTION_ASSURANCE_REPORT.json": b'{"status":"FAIL"}\n'})
    archive = tmp_path / "separate-report.zip"
    count = write_package(archive, files)
    assert verify(archive) == ([], count)


def test_package_cli_ignores_caller_checkout_git_and_release_environment(tmp_path: Path) -> None:
    foreign = tmp_path / "foreign-checkout"
    (foreign / ".git").mkdir(parents=True)
    (foreign / "SOURCE_MANIFEST.json").write_text('{"forged":"caller"}')
    extraction = foreign / "temporary"
    extraction.mkdir()
    fake_bin = foreign / "bin"
    fake_bin.mkdir()
    marker = foreign / "git-was-invoked"
    fake_git = fake_bin / "git"
    fake_git.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\nexit 0\n")
    fake_git.chmod(0o755)
    files = package_files(
        {
            "scripts/verify_source_manifest.py": b"raise RuntimeError('do not execute packaged code')\n"
        }
    )
    archive = tmp_path / "independent.zip"
    count = write_package(archive, files)
    environment = dict(
        os.environ,
        PATH=str(fake_bin),
        TMPDIR=str(extraction),
        GIT_DIR=str(foreign / ".git"),
        GIT_WORK_TREE=str(foreign),
        KORPUS_RELEASE_VERSION="v-foreign-caller",
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_package.py"), str(archive)],
        cwd=foreign,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True and payload["files"] == count
    assert not marker.exists(), "package semantics consulted caller Git state"
