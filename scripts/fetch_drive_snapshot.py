#!/usr/bin/env python3
"""Take a snapshot of a Google Drive folder, with provenance, before anything is ingested.

Fetching is not ingestion, and keeping them apart is the point of this script.

A live dependency on Drive would mean a document can change under the corpus after it was
reviewed: the version the system cites would no longer be the version somebody approved,
and nothing in the answer would say so. So the bytes are pulled once, into a directory,
and every file is recorded with what Drive said about it — file id, modifiedTime, Drive's
own md5 — beside the sha256 of the bytes as they arrived. That record is the answer to
"where did this text come from", and it is written before the importer sees anything.

Re-running is how a change is *noticed*, not applied. A file whose Drive md5 differs from
the snapshot is reported as CHANGED; turning that into a new version, with a revision and
a supersession edge, is a curator's decision and belongs in the review flow.

Transport is rclone, deliberately: it already handles OAuth, shared folders and the
export of Google-native formats, and it runs as an operator tool outside this system's
trust boundary. Putting an OAuth client and a network call inside the ingestion path
would give the parser a reason to reach the internet, which it must never have.

One-time setup, interactive, on the operator's own hands:

    rclone config          # n) new remote, name it `drive`, type `drive`, scope 2 (read-only)

Then:

    python3 scripts/fetch_drive_snapshot.py \\
        --remote drive: --folder-id 14OOIDskQA7UeAWwYwGheY1d7HyW5iobA \\
        --into var/corpus/ml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: What the corpus can actually read. Anything else is listed in the snapshot record and
#: left on disk — naming it is useful, ingesting it is not.
INGESTIBLE = {".txt", ".md", ".json", ".html", ".htm", ".pdf", ".docx"}

#: Google-native documents have no bytes to hash until they are exported. Exported to the
#: formats this corpus reads; a Google Doc becomes a .docx, a Sheet is skipped because a
#: spreadsheet has no prose to quote.
EXPORT_FORMATS = "docx,pdf"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rclone(*arguments: str, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    if shutil.which("rclone") is None:
        raise SystemExit(
            "rclone is not installed. It carries the OAuth flow so this repository does "
            "not have to: https://rclone.org/install/"
        )
    return subprocess.run(
        ["rclone", *arguments], capture_output=True, text=True, check=False, timeout=timeout
    )


def _listing(remote: str, folder_id: str) -> list[dict[str, Any]]:
    """Every file under the folder, with Drive's own metadata, before anything is copied.

    `--drive-root-folder-id` is what makes a *shared* folder addressable: it is not under
    the account's My Drive, so a path expression cannot reach it.
    """
    completed = _rclone(
        "lsjson", remote, "--recursive", "--files-only", "--hash",
        f"--drive-root-folder-id={folder_id}",
    )
    if completed.returncode != 0:
        raise SystemExit(f"rclone lsjson failed: {completed.stderr.strip()[:400]}")
    return list(json.loads(completed.stdout or "[]"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", required=True, help="configured rclone remote, e.g. drive:")
    parser.add_argument("--folder-id", required=True)
    parser.add_argument("--into", type=Path, required=True)
    parser.add_argument("--list-only", action="store_true")
    arguments = parser.parse_args()

    entries = _listing(arguments.remote, arguments.folder_id)
    if arguments.list_only:
        print(
            json.dumps(
                {
                    "files": len(entries),
                    "by_extension": _count_by_extension(entries),
                    "sample": [entry.get("Path") for entry in entries[:20]],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    destination = arguments.into
    destination.mkdir(parents=True, exist_ok=True)
    previous = _load_previous(destination)

    completed = _rclone(
        "copy", arguments.remote, str(destination),
        f"--drive-root-folder-id={arguments.folder_id}",
        f"--drive-export-formats={EXPORT_FORMATS}",
        "--transfers=4", "--checkers=8",
    )
    if completed.returncode != 0:
        raise SystemExit(f"rclone copy failed: {completed.stderr.strip()[:400]}")

    records: list[dict[str, Any]] = []
    changed: list[str] = []
    for entry in sorted(entries, key=lambda item: str(item.get("Path", ""))):
        relative = str(entry.get("Path", ""))
        local = destination / relative
        if not local.is_file():
            # Google-native files land under an exported name; find it by stem.
            candidates = (
                sorted(local.parent.glob(f"{local.stem}.*")) if local.parent.is_dir() else []
            )
            local = candidates[0] if candidates else local
        if not local.is_file():
            records.append({"path": relative, "state": "NOT_FETCHED"})
            continue
        drive_md5 = str(entry.get("Hashes", {}).get("md5") or "")
        record = {
            "path": local.relative_to(destination).as_posix(),
            "drive_path": relative,
            "drive_id": str(entry.get("ID", "")),
            "drive_modified": str(entry.get("ModTime", "")),
            "drive_md5": drive_md5,
            "bytes": local.stat().st_size,
            "sha256": _sha256(local),
            "ingestible": local.suffix.casefold() in INGESTIBLE,
        }
        before = previous.get(record["path"])
        if before is not None and before.get("sha256") != record["sha256"]:
            record["state"] = "CHANGED"
            changed.append(record["path"])
        else:
            record["state"] = "UNCHANGED" if before is not None else "NEW"
        records.append(record)

    snapshot = {
        "schema_version": 1,
        "taken_at": datetime.now(UTC).isoformat(),
        "remote": arguments.remote,
        "folder_id": arguments.folder_id,
        "files": len(records),
        "ingestible": sum(1 for record in records if record.get("ingestible")),
        "changed_since_last_snapshot": changed,
        "records": records,
        "interpretation": (
            "A snapshot, not a sync. A file whose bytes differ from the previous snapshot "
            "is reported as CHANGED and nothing is done about it: turning a changed source "
            "into a new corpus version, with a revision and a supersession edge, is a "
            "curator's decision. Ingesting it silently would replace the text a reviewer "
            "approved with text nobody has read."
        ),
    }
    (destination / "snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    visible = {key: value for key, value in snapshot.items() if key != "records"}
    print(json.dumps(visible, ensure_ascii=False, indent=2))
    return 1 if changed else 0


def _count_by_extension(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        suffix = Path(str(entry.get("Path", ""))).suffix.casefold() or "<none>"
        counts[suffix] = counts.get(suffix, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def _load_previous(destination: Path) -> dict[str, dict[str, Any]]:
    path = destination / "snapshot.json"
    if not path.is_file():
        return {}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(record["path"]): record
        for record in stored.get("records", [])
        if record.get("path")
    }


if __name__ == "__main__":
    sys.exit(main())
