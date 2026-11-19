"""Generated identity bytes have their own exact Git capture, outside source digests."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import github_evidence_source as source  # noqa: E402
import github_source_identity as identity  # noqa: E402

from .hosted_evidence_fixtures import COMMIT, TREE, measured_fixture  # noqa: E402


@pytest.fixture
def identity_git(tmp_path, monkeypatch):
    """Explicit Git subprocess test double; it grants no live checkout authority."""
    records = []
    responses = {}
    for index, name in enumerate(identity.IDENTITY_PATHS, 1):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = ('{"neutral":' + str(index) + "}").encode()
        path.write_bytes(payload)
        path.chmod(0o644)
        oid = str(index) * 40
        records.append(f"100644 blob {oid}\t{name}\0".encode())
        responses[("cat-file", "-s", oid)] = str(len(payload)).encode() + b"\n"
        responses[("cat-file", "blob", oid)] = payload
    listing = ("ls-tree", "-r", "-z", "--full-tree", COMMIT, "--", *identity.IDENTITY_PATHS)
    responses[listing] = b"".join(records)
    calls = []

    def git_bytes(root, *arguments):
        assert root == tmp_path
        calls.append(arguments)
        return responses[arguments]

    monkeypatch.setattr(identity, "_git_bytes", git_bytes)
    return tmp_path, responses, listing, calls


def test_fixed_identity_capture_keeps_exact_committed_bytes_and_modes(identity_git):
    root, _responses, listing, calls = identity_git
    captured = identity.capture_identity_files(root, COMMIT)
    assert tuple(path.as_posix() for path, _mode, _content in captured) == identity.IDENTITY_PATHS
    assert all(
        mode == "0644" and content == (root / path).read_bytes() for path, mode, content in captured
    )
    assert calls[0] == listing and len(calls) == 7


@pytest.mark.parametrize("change", ["missing", "duplicate", "foreign", "symlink", "malformed"])
def test_generated_identity_requires_fixed_regular_commit_census(identity_git, change):
    root, responses, listing, _calls = identity_git
    records = responses[listing].split(b"\0")[:-1]
    if change == "missing":
        records.pop()
    elif change == "duplicate":
        records[-1] = records[0]
    elif change == "foreign":
        records[-1] = records[-1].replace(b"apps/api/src/korpus/release.json", b"foreign.json")
    elif change == "symlink":
        records[0] = records[0].replace(b"100644", b"120000")
    else:
        records[0] = b"not a Git tree record"
    responses[listing] = b"\0".join(records) + b"\0"
    with pytest.raises(ValueError):
        identity.capture_identity_files(root, COMMIT)


@pytest.mark.parametrize("change", ["bytes", "mode", "missing", "symlink"])
def test_identity_working_bytes_and_modes_must_equal_exact_commit(identity_git, change):
    root, _responses, _listing, _calls = identity_git
    path = root / "SOURCE_MANIFEST.json"
    if change == "bytes":
        path.write_bytes(b'{"foreign":true}')
    elif change == "mode":
        path.chmod(0o755)
    else:
        path.unlink()
        if change == "symlink":
            path.symlink_to(root / "PACKAGE_BUILD.json")
    with pytest.raises(ValueError, match="committed bytes or mode"):
        identity.capture_identity_files(root, COMMIT)


@pytest.mark.parametrize(
    "size", [b"0", b"-1", str(identity.MAX_JSON_BYTES + 1).encode(), b"invalid"]
)
def test_identity_blob_size_is_bounded_before_body_read(identity_git, size):
    root, responses, _listing, calls = identity_git
    responses[("cat-file", "-s", "1" * 40)] = size
    with pytest.raises(ValueError):
        identity.capture_identity_files(root, COMMIT)
    assert not any(command[:2] == ("cat-file", "blob") for command in calls)


def test_missing_trusted_git_cannot_capture_generated_identities(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "_command", lambda *args: None)
    with pytest.raises(ValueError, match="trusted Git source identity is unavailable"):
        identity.capture_identity_files(tmp_path, COMMIT)


def test_generated_identity_capture_does_not_expand_existing_digest_scopes(tmp_path, monkeypatch):
    fixture = measured_fixture(tmp_path)
    checkout = fixture.checkout
    monkeypatch.setattr(
        source, "_oid", lambda root, expression: COMMIT if expression == "HEAD^{commit}" else TREE
    )
    monkeypatch.setattr(source, "git_files", lambda root: list(checkout.files))
    monkeypatch.setattr(
        source, "capture_identity_files", lambda root, commit: checkout.identity_files
    )
    first = source.capture_checkout(tmp_path)
    changed = tuple(
        (path, mode, content + b"\n")
        if path.name == "SOURCE_MANIFEST.json"
        else (path, mode, content)
        for path, mode, content in checkout.identity_files
    )
    monkeypatch.setattr(source, "capture_identity_files", lambda root, commit: changed)
    second = source.capture_checkout(tmp_path)
    assert first != second
    assert dataclasses.replace(first, identity_files=changed) == second
