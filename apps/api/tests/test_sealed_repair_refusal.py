from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _run(script: str, database: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--database", str(database), "--apply"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_markup_repair_refuses_a_sealed_span_before_writing(tmp_path: Path) -> None:
    database = tmp_path / "sealed.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        "CREATE TABLE document_versions (id TEXT, review_state TEXT, is_current INTEGER, "
        "evidence_digest TEXT);"
        "CREATE TABLE evidence_spans (id TEXT, version_id TEXT, text TEXT, text_hash TEXT);"
        "INSERT INTO document_versions VALUES ('v','approved',1,'sealed');"
        "INSERT INTO evidence_spans VALUES ('s','v','&lt;p>Справжнє достатньо довге речення для безпечного очищення.','old');"
    )
    connection.commit()
    connection.close()

    completed = _run("repair_span_markup.py", database)
    stored = sqlite3.connect(database).execute("SELECT text FROM evidence_spans").fetchone()[0]

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["status"] == "REFUSED"
    assert stored.startswith("&lt;p>")


def test_respan_refuses_sealed_versions_before_reading_source_objects(tmp_path: Path) -> None:
    database = tmp_path / "sealed.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE document_versions "
        "(id TEXT, object_key TEXT, source_hash TEXT, evidence_digest TEXT)"
    )
    connection.execute("INSERT INTO document_versions VALUES ('v','missing','sha','sealed')")
    connection.commit()
    connection.close()

    completed = _run("respan_from_source.py", database)
    report = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert report["status"] == "REFUSED"
    assert report["sealed_count"] == 1
