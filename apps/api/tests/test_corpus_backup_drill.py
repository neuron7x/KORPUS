"""A backup nobody has restored is a file. This restores one and asks it a question.

The deployment that is actually serving keeps its corpus in SQLite — 1616 documents and
116 229 spans, five hours of import, on one disk with no replica. `backup_postgres.sh`
covers the deployment this system is designed for and not the one it is running in, so
losing the file was not a recovery-time incident but a repeat of the five hours.

Two properties, and the second is the one that matters:

  * the snapshot is consistent while the database is being written to — `cp` on a WAL
    database captures a torn page set and leaves the -wal behind, and the copy opens
    without complaint;
  * the restored database answers. A corpus that restores empty restores *cleanly*, and
    nothing about the running system would say so, which is why the drill checks for
    approved versions and spans rather than for a file.

Run against a small fixture here. The real drill was executed on 2026-08-06 against the
imported corpus: 1.96 GB encrypted, restored to 1616 documents / 1616 approved / 116 229
spans, and the restored copy answered "накладання турнікету" with four citations.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKUP = ROOT / "scripts/backup_sqlite.sh"
RESTORE = ROOT / "scripts/restore_sqlite.sh"


def _corpus(path: Path, documents: int = 3) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE documents (id TEXT PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE document_versions (id TEXT PRIMARY KEY, review_state TEXT)"
        )
        connection.execute("CREATE TABLE evidence_spans (id TEXT PRIMARY KEY, text TEXT)")
        for index in range(documents):
            connection.execute("INSERT INTO documents VALUES (?)", (f"d{index}",))
            connection.execute(
                "INSERT INTO document_versions VALUES (?, 'approved')", (f"v{index}",)
            )
            connection.execute(
                "INSERT INTO evidence_spans VALUES (?, ?)", (f"s{index}", "текст наказу")
            )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def environment(tmp_path: Path) -> dict[str, str]:
    key = tmp_path / "key"
    key.write_text("0" * 64 + "\n", encoding="utf-8")
    key.chmod(0o600)
    return {
        "PATH": "/usr/bin:/bin",
        "KORPUS_BACKUP_ENCRYPTION_KEY_FILE": str(key),
        "KORPUS_BACKUP_KEY_ID": "drill",
        "KORPUS_BACKUP_DIR": str(tmp_path / "backups"),
    }


def _run(script: Path, arguments: list[str], environment: dict[str, str]) -> str:
    completed = subprocess.run(
        ["bash", str(script), *arguments],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        cwd=ROOT,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    return completed.stdout.strip().splitlines()[-1]


def test_a_backup_restores_to_a_corpus_that_can_be_cited(
    tmp_path: Path, environment: dict[str, str]
) -> None:
    database = tmp_path / "korpus.db"
    _corpus(database)
    objects = tmp_path / "objects"
    objects.mkdir()
    (objects / "sha256-abc").write_bytes(b"%PDF-1.4\n")

    backup = _run(
        BACKUP,
        [],
        {
            **environment,
            "KORPUS_BACKUP_SQLITE_PATH": str(database),
            "KORPUS_BACKUP_OBJECT_ROOT": str(objects),
        },
    )
    restored = _run(RESTORE, [backup, str(tmp_path / "restored")], environment)

    assert Path(restored).is_file()
    # The objects travel with the database: citing a passage nobody can open is the
    # failure a database-only backup produces, and it produces it silently.
    assert (tmp_path / "restored/objects/sha256-abc").is_file()


def test_the_drill_refuses_a_corpus_that_restores_empty(
    tmp_path: Path, environment: dict[str, str]
) -> None:
    """The negative control. An empty corpus restores cleanly, which is the whole risk."""
    database = tmp_path / "korpus.db"
    _corpus(database, documents=0)

    backup = _run(
        BACKUP, [], {**environment, "KORPUS_BACKUP_SQLITE_PATH": str(database)}
    )
    completed = subprocess.run(
        ["bash", str(RESTORE), backup, str(tmp_path / "restored")],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        cwd=ROOT,
        timeout=300,
    )

    assert completed.returncode != 0, completed.stdout
    assert "unusable" in completed.stdout + completed.stderr


def test_a_tampered_backup_is_refused_before_it_is_decrypted(
    tmp_path: Path, environment: dict[str, str]
) -> None:
    database = tmp_path / "korpus.db"
    _corpus(database)
    backup = _run(
        BACKUP, [], {**environment, "KORPUS_BACKUP_SQLITE_PATH": str(database)}
    )

    # The file is 0444 by the time it lands: ransomware and a careless script both work
    # by writing, and this is the local half of INF-012's immutability clause. Asserted
    # here rather than assumed, then relaxed so the tamper can happen at all — which is
    # exactly what an attacker with the writer's own privileges would have to do.
    assert Path(backup).stat().st_mode & 0o222 == 0, "the newest backup is writable"
    Path(backup).chmod(0o600)
    payload = bytearray(Path(backup).read_bytes())
    payload[-1] ^= 0xFF
    Path(backup).write_bytes(bytes(payload))

    completed = subprocess.run(
        ["bash", str(RESTORE), backup, str(tmp_path / "restored")],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        cwd=ROOT,
        timeout=300,
    )

    assert completed.returncode != 0
    assert not (tmp_path / "restored/korpus.db").exists(), (
        "a tampered archive produced a database on disk"
    )


if sys.platform not in {"linux", "darwin"}:  # pragma: no cover - the scripts are POSIX
    pytest.skip("shell drill", allow_module_level=True)
