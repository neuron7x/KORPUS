from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from korpus.application import release_claim_git_tree as git_tree
from korpus.application import release_claim_manifest_tree as manifest_tree
from korpus.application.release_claim_tree import tracked_tree_digest

from scripts.manifest_lib.integrity import manifest_root


def _commit(root: Path, value: str) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "source.py").write_text(value, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "source.py"], check=True)
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
            "fixture",
        ],
        check=True,
    )


def test_digest_ignores_git_repository_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _commit(first, "first = True\n")
    _commit(second, "second = True\n")
    expected = tracked_tree_digest(first)
    redirected = tracked_tree_digest(second)
    assert expected is not None and redirected is not None and expected != redirected

    monkeypatch.setenv("GIT_DIR", str(second / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(second))
    monkeypatch.setenv("GIT_INDEX_FILE", str(second / ".git/index"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(second / ".git/objects"))
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", str(second / ".git/objects"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.worktree")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(second))
    assert tracked_tree_digest(first) == expected


def test_digest_overrides_local_core_worktree(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _commit(first, "first = True\n")
    _commit(second, "second = True\n")
    expected = tracked_tree_digest(first)
    subprocess.run(["git", "-C", str(first), "config", "core.worktree", str(second)], check=True)
    assert tracked_tree_digest(first) == expected


def test_digest_refuses_assume_unchanged_dirty_bytes(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _commit(repository, "answer = 1\n")
    assert tracked_tree_digest(repository) is not None
    subprocess.run(
        ["git", "-C", str(repository), "update-index", "--assume-unchanged", "source.py"],
        check=True,
    )
    (repository / "source.py").write_text("answer = 2\n", encoding="utf-8")
    assert tracked_tree_digest(repository) is None


def test_digest_refuses_untracked_source_even_when_ignored(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _commit(repository, "answer = 1\n")
    (repository / ".gitignore").write_text("hidden.py\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", ".gitignore"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=KORPUS test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "ignore declaration",
        ],
        check=True,
    )
    (repository / "hidden.py").write_text("hidden = True\n", encoding="utf-8")
    assert tracked_tree_digest(repository) is None


def test_git_environment_does_not_leak_back_to_process(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _commit(repository, "answer = 1\n")
    before = dict(os.environ)
    assert tracked_tree_digest(repository) is not None
    assert dict(os.environ) == before


def test_digest_refuses_worktree_mode_drift(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _commit(repository, "answer = 1\n")
    assert tracked_tree_digest(repository) is not None
    (repository / "source.py").chmod(0o755)
    assert tracked_tree_digest(repository) is None


def test_digest_refuses_missing_tracked_source(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _commit(repository, "answer = 1\n")
    assert tracked_tree_digest(repository) is not None
    (repository / "source.py").unlink()
    assert tracked_tree_digest(repository) is None


def _gitless_record(root: Path) -> dict[str, object]:
    source = root / "source.py"
    source.write_text("answer = 1\n", encoding="utf-8")
    source.chmod(0o644)
    content = source.read_bytes()
    return {
        "path": "source.py",
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "mode": "0644",
    }


def _write_gitless_manifest(root: Path, records: object) -> None:
    valid = isinstance(records, list) and all(isinstance(item, dict) for item in records)
    document = {
        "schema": "korpus.source-manifest.v2",
        "kind": "source",
        "manifest_self_excluded": True,
        "file_count": len(records) if isinstance(records, list) else 0,
        "root_sha256": manifest_root(records) if valid else "",
        "files": records,
    }
    (root / "SOURCE_MANIFEST.json").write_text(json.dumps(document), encoding="utf-8")


def test_gitless_snapshot_rejects_content_and_mode_drift(tmp_path: Path) -> None:
    record = _gitless_record(tmp_path)
    _write_gitless_manifest(tmp_path, [record])
    assert tracked_tree_digest(tmp_path) is not None
    (tmp_path / "source.py").write_text("tampered\n", encoding="utf-8")
    assert tracked_tree_digest(tmp_path) is None
    (tmp_path / "source.py").write_text("answer = 1\n", encoding="utf-8")
    (tmp_path / "source.py").chmod(0o755)
    assert tracked_tree_digest(tmp_path) is None


@pytest.mark.parametrize("invalid", ["{", "[]", '{"files":"bad"}', '{"files":[null]}'])
def test_gitless_snapshot_rejects_malformed_manifest(tmp_path: Path, invalid: str) -> None:
    _gitless_record(tmp_path)
    (tmp_path / "SOURCE_MANIFEST.json").write_text(invalid, encoding="utf-8")
    assert tracked_tree_digest(tmp_path) is None


@pytest.mark.parametrize(
    ("key", "bad"),
    [("sha256", "0" * 64), ("bytes", -1), ("mode", "0000")],
)
def test_gitless_snapshot_rejects_false_records(tmp_path: Path, key: str, bad: object) -> None:
    record = _gitless_record(tmp_path)
    record[key] = bad
    _write_gitless_manifest(tmp_path, [record])
    assert tracked_tree_digest(tmp_path) is None


@pytest.mark.parametrize("path", ["/evil.py", "../evil.py", "dist/excluded.py"])
def test_manifest_record_refuses_unsafe_path(tmp_path: Path, path: str) -> None:
    record = _gitless_record(tmp_path)
    record["path"] = path
    assert manifest_tree.manifest_record((tmp_path, record)) is None


def test_gitless_snapshot_rejects_duplicate_and_missing_files(tmp_path: Path) -> None:
    record = _gitless_record(tmp_path)
    _write_gitless_manifest(tmp_path, [record, record])
    assert tracked_tree_digest(tmp_path) is None
    (tmp_path / "source.py").unlink()
    _write_gitless_manifest(tmp_path, [record])
    assert tracked_tree_digest(tmp_path) is None


@pytest.mark.parametrize(
    "marker_kind",
    ["missing", "symlink", "garbage", "missing_target", "invalid_utf8", "multiline", "not_dir"],
)
def test_git_directory_marker_rejects_invalid_redirects(tmp_path: Path, marker_kind: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    marker = root / ".git"
    storage = tmp_path / "storage"
    if marker_kind == "missing":
        pass
    elif marker_kind == "symlink":
        storage.mkdir()
        marker.symlink_to(storage, target_is_directory=True)
    elif marker_kind == "garbage":
        marker.write_text("unexpected", encoding="utf-8")
    elif marker_kind == "missing_target":
        marker.write_text("gitdir: ../storage\n", encoding="utf-8")
    elif marker_kind == "invalid_utf8":
        marker.write_bytes(b"\xff")
    elif marker_kind == "multiline":
        marker.write_text("gitdir: ../storage\nextra\n", encoding="utf-8")
    else:
        storage.write_text("not a gitdir", encoding="utf-8")
        marker.write_text("gitdir: ../storage\n", encoding="utf-8")
    assert git_tree._git_directory(root) is None


def test_git_directory_marker_accepts_both_worktree_forms(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    marker = root / ".git"
    storage = tmp_path / "storage"
    storage.mkdir()
    for target in ("../storage", str(storage)):
        marker.write_text(f"gitdir: {target}\n", encoding="utf-8")
        assert git_tree._git_directory(root) == storage.resolve()
    marker.unlink()
    marker.mkdir()
    assert git_tree._git_directory(root) == marker.resolve()


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"100644 tree abc\tsource.py",
        b"100644 blob abc\t../evil.py",
        b"100644 blob abc\t/evil.py",
        b"100644 blob abcsource.py",
        b"not metadata\tsource.py",
        b"100644 blob abc\t\xff",
    ],
)
def test_tree_record_parser_refuses_malformed_input(raw: bytes) -> None:
    assert git_tree._record(raw) is None


def test_tree_record_parser_preserves_exec_and_symlink_modes() -> None:
    assert git_tree._record(b"100644 blob abc\tsource.py") == (Path("source.py"), "0644", "abc")
    assert git_tree._record(b"100755 blob abc\texecutable.sh") == (
        Path("executable.sh"),
        "0755",
        "abc",
    )
    assert git_tree._record(b"120000 blob abc\tlink") == (Path("link"), "120000", "abc")


def test_tree_listing_refuses_duplicates_and_excluded_only_entries() -> None:
    valid = b"100644 blob abc\tsource.py\0"
    assert git_tree._tree_records(valid) == [(Path("source.py"), "0644", "abc")]
    assert git_tree._tree_records(valid + valid) is None
    assert git_tree._tree_records(b"100644 blob abc\treports/old.json\0") is None
    assert git_tree._tree_records(b"not a record\0") is None
    assert git_tree._tree_records(b"") is None


def test_worktree_file_types_measured_without_following_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("safe\n", encoding="utf-8")
    source.chmod(0o644)
    assert git_tree._working_file(source) == ("0644", b"safe\n")
    source.chmod(0o755)
    assert git_tree._working_file(source) == ("0755", b"safe\n")
    link = tmp_path / "linked.py"
    link.symlink_to("source.py")
    assert git_tree._working_file(link) == ("120000", b"source.py")
    assert git_tree._working_file(tmp_path) is None
    assert git_tree._working_file(tmp_path / "missing.py") is None


def test_worktree_enumeration_rejects_untracked_and_ignored_source(
    tmp_path: Path,
) -> None:
    (tmp_path / "source.py").write_text("safe\n", encoding="utf-8")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "generated.json").write_text("{}", encoding="utf-8")
    assert git_tree._working_paths(tmp_path) == [Path("source.py")]
    (tmp_path / "ignored.py").write_text("unsafe\n", encoding="utf-8")
    assert git_tree._working_paths(tmp_path) == [Path("ignored.py"), Path("source.py")]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"abc blob 1\nx\n", [b"x"]),
        (b"abc blob 1\nx\nextra", None),
        (b"def blob 1\nx\n", None),
        (b"abc tree 1\nx\n", None),
        (b"abc blob 2\nx\n", None),
        (b"abc blob 1\nx?", None),
        (b"malformed\n", None),
    ],
)
def test_git_blob_batch_rejects_forged_framing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: bytes, expected: object
) -> None:
    monkeypatch.setattr(git_tree, "_command", lambda *_args: (["git"], {}))
    monkeypatch.setattr(
        git_tree.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=payload),
    )
    assert git_tree._blob_bytes(tmp_path, ["abc"]) == expected


@pytest.mark.parametrize("failure", ["untrusted_binary", "invalid_tree", "missing_object"])
def test_git_tree_rejects_missing_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _commit(root, "answer = 1\n")
    if failure == "untrusted_binary":
        monkeypatch.setattr(git_tree, "git_executable", lambda: None)
    elif failure == "invalid_tree":
        monkeypatch.setattr(git_tree, "_tree_records", lambda _listing: None)
    else:
        monkeypatch.setattr(git_tree, "_blob_bytes", lambda _root, _objects: None)
    assert git_tree.git_files(root) is None


@pytest.mark.parametrize(
    ("key", "invalid"),
    [
        ("schema", "wrong.schema"),
        ("kind", "distribution"),
        ("manifest_self_excluded", False),
        ("file_count", 0),
        ("root_sha256", "0" * 64),
    ],
)
def test_gitless_manifest_header_must_be_bound(tmp_path: Path, key: str, invalid: object) -> None:
    record = _gitless_record(tmp_path)
    _write_gitless_manifest(tmp_path, [record])
    path = tmp_path / "SOURCE_MANIFEST.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data[key] = invalid
    path.write_text(json.dumps(data), encoding="utf-8")
    assert tracked_tree_digest(tmp_path) is None


def test_gitless_snapshot_rejects_unlisted_included_source(tmp_path: Path) -> None:
    record = _gitless_record(tmp_path)
    _write_gitless_manifest(tmp_path, [record])
    assert tracked_tree_digest(tmp_path) is not None
    (tmp_path / "unlisted.py").write_text("data = 2\n", encoding="utf-8")
    assert tracked_tree_digest(tmp_path) is None


def test_gitless_snapshot_rejects_external_symlink_with_matching_bytes(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    root.mkdir()
    record = _gitless_record(root)
    _write_gitless_manifest(root, [record])
    assert tracked_tree_digest(root) is not None
    outside = tmp_path / "outside.py"
    outside.write_bytes((root / "source.py").read_bytes())
    (root / "source.py").unlink()
    (root / "source.py").symlink_to(outside)
    assert tracked_tree_digest(root) is None


def test_gitless_snapshot_refuses_dangling_git_marker(tmp_path: Path) -> None:
    record = _gitless_record(tmp_path)
    _write_gitless_manifest(tmp_path, [record])
    assert tracked_tree_digest(tmp_path) is not None
    (tmp_path / ".git").symlink_to(tmp_path / "missing-object-database")
    assert tracked_tree_digest(tmp_path) is None


def test_manifest_record_requires_canonical_relative_path(tmp_path: Path) -> None:
    record = _gitless_record(tmp_path)
    record["path"] = "./source.py"
    assert manifest_tree.manifest_record((tmp_path, record)) is None

@pytest.mark.parametrize(
    ("target", "poison"),
    [
        ('"kind": "source"', '"kind": "distribution", "kind": "source"'),
        ('"mode": "0644"', '"mode": "0755", "mode": "0644"'),
        ('"path": "source.py"', '"path": "../outside", "path": "source.py"'),
    ],
)
def test_gitless_manifest_rejects_duplicate_json_keys(
    tmp_path: Path, target: str, poison: str
) -> None:
    record = _gitless_record(tmp_path)
    _write_gitless_manifest(tmp_path, [record])
    assert tracked_tree_digest(tmp_path) is not None
    file = tmp_path / "SOURCE_MANIFEST.json"
    original = file.read_text(encoding="utf-8")
    assert target in original
    file.write_text(original.replace(target, poison, 1), encoding="utf-8")
    assert tracked_tree_digest(tmp_path) is None


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("file_count", 1.0),
        ("file_count", True),
        ("manifest_self_excluded", 1),
    ],
)
def test_gitless_manifest_refuses_header_type_coercion(
    tmp_path: Path, field: str, invalid: object
) -> None:
    record = _gitless_record(tmp_path)
    _write_gitless_manifest(tmp_path, [record])
    payload_path = tmp_path / "SOURCE_MANIFEST.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload[field] = invalid
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    assert tracked_tree_digest(tmp_path) is None


def test_gitless_manifest_refuses_noninteger_record_byte_count(tmp_path: Path) -> None:
    record = _gitless_record(tmp_path)
    record["bytes"] = float(record["bytes"])
    _write_gitless_manifest(tmp_path, [record])
    assert tracked_tree_digest(tmp_path) is None
