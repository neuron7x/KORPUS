"""Pinned build inputs fail closed before any diagnostic executable is admitted."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

from scripts import scanner_stdlib_build as build
from scripts import scanner_stdlib_identity as identity
from scripts.scanner_stdlib_pins import PATCHES

ROOT = Path(__file__).resolve().parents[3]


def test_exact_patch_bytes_and_optional_prefix_scope() -> None:
    for name, expected in PATCHES.values():
        assert identity.digest(ROOT / "config/scanner-diagnostics" / name) == expected
    patch = (ROOT / "config/scanner-diagnostics/gitleaks-optional-prefix.patch").read_text()
    assert "r.Regex.String() == precheck.expected" in patch
    assert "TestOptionalPrefixInPlaceRegexMutationFallsBack" in patch
    assert "TestOptionalPrefixCompleteFindingEquivalence" in patch
    assert "original FindAllStringIndex" not in patch  # no substitute finder is introduced
    assert "for _, matchIndex := range r.Regex.FindAllStringIndex(currentRaw, -1)" not in patch


@pytest.mark.parametrize("change", ["bytes", "mode", "symlink", "extra"])
def test_complete_source_inventory_detects_each_material_change(
    tmp_path, monkeypatch, change
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    entry = source / "rule.txt"
    entry.write_text("neutral exact input")
    expected = identity.tree_inventory(source)
    monkeypatch.setattr(identity, "SOURCE_INVENTORIES", {"control": expected["sha256"]})
    monkeypatch.setattr(identity, "UNCHANGED_FILES", {"rule.txt": identity.digest(entry)})
    assert identity.source_identity(source, "control") == expected
    if change == "bytes":
        entry.write_text("changed input")
    elif change == "mode":
        entry.chmod(0o755)
    elif change == "symlink":
        entry.unlink()
        entry.symlink_to("elsewhere")
    else:
        (source / "extra.go").write_text("unexpected source")
    with pytest.raises(ValueError):
        identity.source_identity(source, "control")


def test_compiler_symlink_and_unknown_binary_are_refused_before_execution(
    tmp_path, monkeypatch
) -> None:
    binary = tmp_path / "go"
    binary.write_bytes(b"not the pinned compiler")
    monkeypatch.setattr(identity.shutil, "which", lambda _: str(binary))
    with pytest.raises(ValueError, match="executable digest"):
        identity.compiler_identity()
    (tmp_path / "link").symlink_to("go")
    with pytest.raises(ValueError, match="symlink"):
        identity.tree_inventory(tmp_path, compiler=True)


def test_build_environment_drops_tokens_and_alternate_engine_flags(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "neutral unit sentinel")
    monkeypatch.setenv("GOFLAGS", "-tags=gore2regex")
    environment = build.build_environment(tmp_path / "go/bin/go", tmp_path)
    assert "GITHUB_TOKEN" not in environment and "HOME" not in environment
    assert environment["GOFLAGS"] == "" and environment["GOTOOLCHAIN"] == "local"
    assert environment["GOENV"] == "off" and environment["CGO_ENABLED"] == "0"
    assert environment["GOMAXPROCS"] == "2"


@pytest.mark.parametrize("code,timed_out", [(1, False), (124, True), (None, True)])
def test_bounded_build_failure_never_becomes_a_success(
    tmp_path, monkeypatch, code, timed_out
) -> None:
    monkeypatch.setattr(
        build, "run_bounded", lambda *_a, **_kw: (code, "unit output", "", timed_out, "unit")
    )
    commands = build.BuildCommands({}, time.monotonic() + 30)
    with pytest.raises(ValueError, match="command failed"):
        commands.run("unit", ["unit-command"], tmp_path)
    assert commands.executions[0]["exit_code"] == code
    assert "unit output" not in json.dumps(commands.executions)


def test_expired_build_deadline_stops_before_spawn(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        build, "run_bounded", lambda *_a, **_kw: pytest.fail("spawned after deadline")
    )
    with pytest.raises(ValueError, match="deadline"):
        build.BuildCommands({}, time.monotonic() - 1).run("unit", ["unit"], tmp_path)


def test_patch_digest_mismatch_stops_before_git_apply(tmp_path) -> None:
    name, _ = PATCHES["candidate"]
    directory = tmp_path / "config/scanner-diagnostics"
    directory.mkdir(parents=True)
    (directory / name).write_text("unexpected patch")
    commands = build.BuildCommands({}, time.monotonic() + 30)
    with pytest.raises(ValueError, match="patch bytes"):
        build.apply_patch(tmp_path, tmp_path, "candidate", commands, ["unused-git"])
    assert commands.executions == []


def test_nonstdlib_selected_source_stops_before_test_or_build(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(build, "source_identity", lambda *_: {"sha256": "a" * 64})
    calls = []

    class Commands:
        def run(self, label, command, cwd):
            calls.append(label)
            return json.dumps({"GoFiles": ["gore2_regex.go"]})

    with pytest.raises(ValueError, match="non-stdlib"):
        build.build_variant(tmp_path, tmp_path, "candidate", tmp_path / "go", Commands())
    assert calls == ["candidate-engine-source"]


def test_inventory_hash_is_independent_of_creation_order(tmp_path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    for root, names in ((first, ("a", "b")), (second, ("b", "a"))):
        root.mkdir()
        for name in names:
            (root / name).write_text(name)
    assert identity.tree_inventory(first) == identity.tree_inventory(second)
    assert identity.digest(first / "a") == hashlib.sha256(b"a").hexdigest()
