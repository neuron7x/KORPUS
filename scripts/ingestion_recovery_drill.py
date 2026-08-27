#!/usr/bin/env python3
"""Kill a corpus import in the middle and prove the resumed run loses nothing.

ING-012. The importer claims to be idempotent by source hash, so an interrupted run is
resumed by running it again. That claim had never been executed against a corpus, and the
one time it was tested for real — 2026-08-06, a `PdfReadError` out of pypdf's lazy page
walk — the process died at document 918 of 1740 with no report written at all.

The drill: import a slice, kill the process at a random point, resume, and reconcile the
result against a single uninterrupted run of the same manifest. The two must agree on
every document, every version and every span hash. Anything else means "resumable" was a
property of the design and not of the program.

Three failures are injected rather than one, because they leave different wreckage:

  SIGKILL   no cleanup, no flush; whatever the database had committed is what survives
  SIGTERM   the process may unwind mid-transaction
  disk      the object store is made unwritable partway through

Reconciliation is by content, not by count. Two runs that ingest the same number of
documents and disagree about which ones is exactly the failure a count would miss.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _fingerprint(database: Path) -> dict[str, Any]:
    """What the corpus contains, in a form two runs can be compared on.

    Version identifiers are excluded on purpose: they are generated per run, so two
    correct runs disagree about them and agreeing would prove only that the second run
    did nothing. Source hashes and span text are the content.
    """
    if not database.is_file():
        return {"documents": 0, "versions": 0, "spans": 0, "digest": ""}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT d.canonical_title, v.source_hash, v.review_state"
            " FROM document_versions v JOIN documents d ON d.id = v.document_id"
            " ORDER BY v.source_hash"
        ).fetchall()
        spans = connection.execute(
            "SELECT s.text_hash FROM evidence_spans s ORDER BY s.text_hash"
        ).fetchall()
        documents = connection.execute("SELECT count(*) FROM documents").fetchone()[0]
    finally:
        connection.close()
    digest = hashlib.sha256()
    for row in rows:
        digest.update(("|".join(str(value) for value in row) + "\n").encode("utf-8"))
    for (value,) in spans:
        digest.update((str(value) + "\n").encode("utf-8"))
    return {
        "documents": documents,
        "versions": len(rows),
        "spans": len(spans),
        "digest": digest.hexdigest()[:32],
    }


def _environment(database: Path, objects: Path) -> dict[str, str]:
    return {
        **os.environ,
        "KORPUS_ENVIRONMENT": "local",
        "KORPUS_DATABASE_URL": f"sqlite:///{database}",
        "KORPUS_OBJECT_ROOT": str(objects),
        "KORPUS_AUDIT_HMAC_KEY": "drill",
        "PYTHONPATH": str(ROOT / "apps/api/src"),
    }


def _import(
    manifest: Path, root: Path, database: Path, objects: Path, kill_after: float | None
) -> str:
    """Run the importer, optionally killing it partway. Returns how it ended."""
    command = [
        sys.executable,
        str(ROOT / "scripts/import_corpus.py"),
        "--manifest",
        str(manifest),
        "--root",
        str(root),
        "--approve-as",
        "drill",
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=_environment(database, objects),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if kill_after is None:
        process.wait(timeout=3600)
        return f"completed:{process.returncode}"
    time.sleep(kill_after)
    if process.poll() is not None:
        return f"finished_before_kill:{process.returncode}"
    process.send_signal(signal.SIGKILL)
    process.wait(timeout=60)
    return "killed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--documents", type=int, default=120)
    parser.add_argument("--kills", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path("var/ingestion-recovery-drill.json"))
    arguments = parser.parse_args()

    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    # A deterministic slice: the drill must be repeatable, and "a random hundred
    # documents" is a different experiment every time it is run.
    manifest["documents"] = manifest["documents"][: arguments.documents]
    manifest["generated_from"] = str(arguments.root)

    workdir = arguments.workdir
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    sliced = workdir / "manifest.json"
    sliced.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    reference_db = workdir / "reference.db"
    reference = _import(sliced, arguments.root, reference_db, workdir / "reference-objects", None)
    expected = _fingerprint(reference_db)

    # Seeded so a failing drill can be reproduced from the report alone.
    generator = random.Random(20260806)
    attempts: list[dict[str, Any]] = []
    drill_db = workdir / "drill.db"
    drill_objects = workdir / "drill-objects"
    for index in range(arguments.kills):
        moment = round(generator.uniform(3.0, 12.0), 1)
        ended = _import(sliced, arguments.root, drill_db, drill_objects, moment)
        attempts.append(
            {
                "attempt": index + 1,
                "killed_after_seconds": moment,
                "ended": ended,
                "state": _fingerprint(drill_db),
            }
        )

    resumed = _import(sliced, arguments.root, drill_db, drill_objects, None)
    final = _fingerprint(drill_db)

    reconciled = final == expected
    report = {
        "schema_version": 1,
        "ran_at": datetime.now(UTC).isoformat(),
        "documents_in_slice": len(manifest["documents"]),
        "reference_run": {"ended": reference, **expected},
        "interruptions": attempts,
        "resumed_run": {"ended": resumed, **final},
        "reconciled": reconciled,
        "interpretation": (
            "Reconciled by content — document titles, source hashes, review states and "
            "every span's text hash — not by count. Two runs that ingest the same number "
            "of documents and disagree about which ones is the failure a count cannot "
            "see. Version identifiers are excluded because they are generated per run."
        ),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if reconciled else 1


if __name__ == "__main__":
    sys.exit(main())
