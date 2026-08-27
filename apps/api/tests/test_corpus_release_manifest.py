"""Which corpus answered this, six months from now, without the running system.

DATA-003 and SRE-007. An answer carries a `corpus_release` — sixteen hex characters
naming the set of versions it could have been drawn from — but nothing outside the process
could say what that release *was*. "The system told me X on 3 August" is answerable only
if the corpus of 3 August can be identified, by something nobody can quietly edit.

Executed against the real corpus on 2026-08-06: 1648 versions, 118 622 spans, release
`d9719c88a62f0cdb`. Verified against the live database (PASS), against a restored backup
taken before the last import (FAIL, `687c571953f6c2be`, 1616 versions — which is the
rollback-detection property working), and against a manifest with one `authority` changed
from `analytical` to `official_ua` (signature broken).

That last case is the one the mechanism exists for. Raising a source's authority class is
the smallest edit that changes what the system will say, because authority decides whether
a source may govern an answer at all — and it is invisible in a diff of a file nobody
signed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "scripts/corpus_release.py"


def _corpus(path: Path, *, versions: int = 3, authority: str = "analytical") -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE documents (id TEXT PRIMARY KEY, canonical_title TEXT,"
            " corpus_id TEXT, classification TEXT, access_tier INT)"
        )
        connection.execute(
            "CREATE TABLE document_versions (id TEXT PRIMARY KEY, document_id TEXT,"
            " source_hash TEXT, revision TEXT, authority TEXT, review_state TEXT,"
            " effective_from TEXT, publication_date TEXT, effective_until TEXT,"
            " rescinded_at TEXT)"
        )
        connection.execute("CREATE TABLE evidence_spans (id TEXT PRIMARY KEY, version_id TEXT)")
        for index in range(versions):
            connection.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?)",
                (f"d{index}", f"Наказ {index}", "public", "public", 0),
            )
            connection.execute(
                "INSERT INTO document_versions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    f"v{index}",
                    f"d{index}",
                    f"{index:064d}",
                    "1",
                    authority,
                    "approved",
                    "2024-01-01",
                    None,
                    None,
                    None,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_spans VALUES (?,?)", (f"s{index}", f"v{index}")
            )
        connection.commit()
    finally:
        connection.close()


def _run(arguments: list[str], key: Path) -> tuple[int, dict[str, object]]:
    completed = subprocess.run(
        [sys.executable, str(TOOL), *arguments, "--key-file", str(key)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        timeout=300,
    )
    payload = json.loads(completed.stdout) if completed.stdout.strip() else {}
    return completed.returncode, payload


@pytest.fixture
def key(tmp_path: Path) -> Path:
    path = tmp_path / "release.key"
    path.write_text("f" * 64, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_a_frozen_release_verifies_against_the_corpus_it_names(tmp_path: Path, key: Path) -> None:
    database = tmp_path / "korpus.db"
    _corpus(database)
    manifest = tmp_path / "release.json"

    code, _ = _run(["freeze", "--database", str(database), "--out", str(manifest)], key)
    assert code == 0

    code, result = _run(["verify", "--manifest", str(manifest), "--database", str(database)], key)
    assert code == 0, result
    assert result["status"] == "PASS", result


def test_a_different_corpus_is_reported_as_a_different_release(tmp_path: Path, key: Path) -> None:
    """The rollback-detection property: after a restore, which corpus is this?"""
    database = tmp_path / "korpus.db"
    _corpus(database, versions=3)
    manifest = tmp_path / "release.json"
    _run(["freeze", "--database", str(database), "--out", str(manifest)], key)

    older = tmp_path / "older.db"
    _corpus(older, versions=2)

    code, result = _run(["verify", "--manifest", str(manifest), "--database", str(older)], key)

    assert code != 0
    assert result["matches_database"] is False
    assert result["database_release"] != result["corpus_release"], result


def test_raising_an_authority_class_breaks_the_signature(tmp_path: Path, key: Path) -> None:
    """The smallest edit that changes what the system will say.

    `authority` decides whether a source may govern an answer at all. Moving one version
    from `analytical` to `official_ua` changes every answer it appears in and is invisible
    in a file nobody signed.
    """
    database = tmp_path / "korpus.db"
    _corpus(database)
    manifest = tmp_path / "release.json"
    _run(["freeze", "--database", str(database), "--out", str(manifest)], key)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["entries"][0]["authority"] = "official_ua"
    manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    code, result = _run(["verify", "--manifest", str(manifest)], key)

    assert code != 0
    assert result["signature_intact"] is False, result


def test_a_manifest_signed_with_another_key_does_not_verify(tmp_path: Path, key: Path) -> None:
    """The control: without this, "the signature holds" could mean "nothing is checked"."""
    database = tmp_path / "korpus.db"
    _corpus(database)
    manifest = tmp_path / "release.json"
    _run(["freeze", "--database", str(database), "--out", str(manifest)], key)

    other = tmp_path / "other.key"
    other.write_text("a" * 64, encoding="utf-8")

    code, result = _run(["verify", "--manifest", str(manifest)], other)

    assert code != 0
    assert result["signature_intact"] is False


def test_the_signer_is_recorded_as_an_assertion(tmp_path: Path, key: Path) -> None:
    """An HMAC proves the file was not altered. It does not prove who approved a corpus."""
    database = tmp_path / "korpus.db"
    _corpus(database)
    manifest = tmp_path / "release.json"
    _run(
        ["freeze", "--database", str(database), "--out", str(manifest), "--signer", "Петренко"],
        key,
    )

    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["declared_signer"]["name"] == "Петренко"
    assert payload["declared_signer"]["verified"] is False
