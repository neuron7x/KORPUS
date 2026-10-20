"""Gitless source digest must reject forged inventories before hashing any source claim."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import source_digest as digest
from scripts.manifest_lib.integrity import file_record, manifest_root


def _manifest(root: Path, records: list[dict[str, object]]) -> None:
    payload = {
        "schema": "korpus.source-manifest.v2",
        "kind": "source",
        "manifest_self_excluded": True,
        "file_count": len(records),
        "root_sha256": manifest_root(records),
        "files": records,
    }
    (root / "SOURCE_MANIFEST.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _seed(root: Path) -> list[dict[str, object]]:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    record = file_record(source, Path("source.py"), source=True)
    _manifest(root, [record])
    return [record]


def _gitless(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(digest, "ROOT", root)
    monkeypatch.setattr(digest, "_git_paths", lambda _ref: None)


def _expected(root: Path, filenames: list[str]) -> str:
    hasher = hashlib.sha256()
    for name in filenames:
        raw = name.encode("utf-8")
        content = (root / name).read_bytes()
        hasher.update(len(raw).to_bytes(4, "big"))
        hasher.update(raw)
        hasher.update(len(content).to_bytes(8, "big"))
        hasher.update(content)
    return hasher.hexdigest()


def test_valid_gitless_archive_hashes_exact_verified_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    _gitless(monkeypatch, tmp_path)
    assert digest.included_paths() == [Path("source.py")]
    assert digest.source_tree_digest() == _expected(tmp_path, ["source.py"])


@pytest.mark.parametrize(
    "poison",
    [
        "unlisted-source",
        "duplicate-record",
        "wrong-mode",
        "wrong-root",
        "wrong-count",
        "duplicate-json-key",
        "changed-bytes",
        "symlink",
        "git-marker",
    ],
)
def test_gitless_source_digest_refuses_ambiguous_or_substituted_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, poison: str
) -> None:
    records = _seed(tmp_path)
    _gitless(monkeypatch, tmp_path)
    if poison == "unlisted-source":
        (tmp_path / "hidden.py").write_text("unexpected = 1\n", encoding="utf-8")
    elif poison == "duplicate-record":
        _manifest(tmp_path, [records[0], records[0]])
    elif poison == "wrong-mode":
        records[0]["mode"] = "0755"
        _manifest(tmp_path, records)
    elif poison == "wrong-root":
        payload = json.loads((tmp_path / "SOURCE_MANIFEST.json").read_text())
        payload["root_sha256"] = "0" * 64
        (tmp_path / "SOURCE_MANIFEST.json").write_text(json.dumps(payload))
    elif poison == "wrong-count":
        payload = json.loads((tmp_path / "SOURCE_MANIFEST.json").read_text())
        payload["file_count"] = True
        (tmp_path / "SOURCE_MANIFEST.json").write_text(json.dumps(payload))
    elif poison == "duplicate-json-key":
        path = tmp_path / "SOURCE_MANIFEST.json"
        text = path.read_text()
        assert '"kind": "source"' in text
        path.write_text(text.replace('"kind": "source"', '"kind": "forged", "kind": "source"'))
    elif poison == "changed-bytes":
        (tmp_path / "source.py").write_text("value = 999\n", encoding="utf-8")
    elif poison == "symlink":
        (tmp_path / "outside.py").write_text("outside = 1\n", encoding="utf-8")
        (tmp_path / "alias.py").symlink_to(tmp_path / "outside.py")
    else:
        (tmp_path / ".git").mkdir()
    with pytest.raises(RuntimeError, match="manifest|git metadata"):
        digest.source_tree_digest()
    with pytest.raises(RuntimeError, match="manifest|git metadata"):
        digest.included_paths()


def test_snapshot_digest_consumes_the_validated_bytes_not_a_second_file_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    _gitless(monkeypatch, tmp_path)
    from korpus.application import release_claim_manifest_tree as gate

    genuine = gate.manifest_files

    def mutate_after_validation(root: Path):
        result = genuine(root)
        assert result is not None
        (root / "source.py").write_text("post-check tamper\n", encoding="utf-8")
        return result

    monkeypatch.setattr(digest, "manifest_files", mutate_after_validation)
    assert digest.source_tree_digest() == _expected_bytes("source.py", b"value = 1\n")


def _expected_bytes(filename: str, content: bytes) -> str:
    hasher = hashlib.sha256()
    raw = filename.encode("utf-8")
    hasher.update(len(raw).to_bytes(4, "big"))
    hasher.update(raw)
    hasher.update(len(content).to_bytes(8, "big"))
    hasher.update(content)
    return hasher.hexdigest()
