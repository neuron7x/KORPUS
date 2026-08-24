#!/usr/bin/env python3
"""Snapshot a *publicly shared* Google Drive folder, with provenance, before anything is ingested.

The companion to `fetch_drive_snapshot.py`, for the case where the folder is shared with
"anyone with the link". That case does not need OAuth, an account, or rclone: Drive's own
web viewer reads such a folder through a browser API key that the folder page itself
carries, and this asks the same question the same way. Nothing here is a bypass — a folder
that is not public returns 404 and the script stops.

Fetching is not ingestion, and keeping them apart is the point. A live dependency on Drive
would mean a document can change under the corpus after it was reviewed: the version the
system cites would no longer be the version somebody approved, and nothing in the answer
would say so. So the bytes are pulled once, into a directory, and every file is recorded
with what Drive said about it — file id, modifiedTime, Drive's own md5 — beside the sha256
of the bytes as they arrived.

Re-running is how a change is *noticed*, not applied. A file whose bytes differ from the
snapshot is reported as CHANGED; turning that into a new version, with a revision and a
supersession edge, is a curator's decision and belongs in the review flow.

    python3 scripts/fetch_drive_public.py --folder-id <ID> --into var/corpus/ml --list-only
    python3 scripts/fetch_drive_public.py --folder-id <ID> --into var/corpus/ml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: What the corpus can actually read. Anything else is recorded in the snapshot and left
#: alone — naming it is useful, downloading it is not.
INGESTIBLE = {".txt", ".md", ".json", ".html", ".htm", ".pdf", ".docx"}

#: Google-native documents have no bytes until they are exported. A Doc becomes a .docx; a
#: Sheet and a Slide deck are listed and skipped, because neither has prose to quote.
EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
}

FOLDER_MIME = "application/vnd.google-apps.folder"

#: Drive's own web viewer authenticates its listing calls with a browser API key served
#: inside the folder page. Read from the page rather than hard-coded: a key baked into
#: this file would be a credential this repository has to own and rotate, and it would
#: rot silently the day Google changes it.
_API_KEY_PATTERN = re.compile(r'"(AIza[0-9A-Za-z_\-]{35})"')

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) korpus-drive-snapshot/1"

#: Anonymous quota is per-IP and unlisted. Backoff is exponential on 403/429/5xx and the
#: run fails loudly rather than writing a snapshot with holes in it: a partial corpus that
#: reports itself as whole is worse than no corpus.
_RETRY_STATUS = {408, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 5

#: 403 is two different answers wearing one number. "rateLimitExceeded" is transient and
#: worth waiting for; "Requests from referer <empty> are blocked" is permanent, and
#: retrying it five times with exponential backoff spent half a minute per candidate key
#: during discovery to learn what the first response already said.
_TRANSIENT_403 = ("ratelimit", "quota", "userratelimit", "backenderror")

#: A single file large enough to be a disk-exhaustion hazard is refused by name rather
#: than streamed. The corpus reads documents, not disk images.
_MAX_FILE_BYTES = 512 * 1024 * 1024


class DriveError(RuntimeError):
    pass


def _is_transient_403(error: urllib.error.HTTPError) -> bool:
    """Whether waiting could change the answer. When the body says nothing, assume not."""
    try:
        body = error.read().decode("utf-8", errors="replace").casefold()
    except (OSError, ValueError):
        return False
    return any(marker in body for marker in _TRANSIENT_403)


def _request(url: str, *, timeout: int = 120) -> bytes:
    delay = 2.0
    last: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as error:
            last = error
            if error.code == 403 and not _is_transient_403(error):
                raise DriveError(f"HTTP 403 for {url.split('?')[0]}") from error
            if error.code != 403 and error.code not in _RETRY_STATUS:
                raise DriveError(f"HTTP {error.code} for {url.split('?')[0]}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = error
        if attempt < _MAX_ATTEMPTS:
            time.sleep(delay)
            delay *= 2
    raise DriveError(f"{last} after {_MAX_ATTEMPTS} attempts: {url.split('?')[0]}")


def discover_api_key(folder_id: str) -> str:
    """Read the browser key out of the folder page, and prove the folder is public doing it."""
    page = _request(f"https://drive.google.com/drive/folders/{folder_id}").decode(
        "utf-8", errors="replace"
    )
    keys = _API_KEY_PATTERN.findall(page)
    if not keys:
        raise DriveError(
            "no API key in the folder page — the folder is probably not shared publicly"
        )
    # Several keys are embedded and only one answers drive/v3 anonymously; the others are
    # referer-locked or first-party. Probing is cheaper than guessing which is which, and
    # it is the same probe that tells us the folder is readable at all.
    for key in dict.fromkeys(str(candidate) for candidate in keys):
        try:
            _list_page(folder_id, key, None)
        except DriveError:
            continue
        return key
    raise DriveError("no embedded key could list this folder anonymously")


def _list_page(folder_id: str, key: str, token: str | None) -> dict[str, Any]:
    query = {
        "q": f"'{folder_id}' in parents and trashed=false",
        "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime)",
        "pageSize": "1000",
        "orderBy": "folder,name",
        "key": key,
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    if token:
        query["pageToken"] = token
    payload = _request(
        "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(query), timeout=60
    )
    body = json.loads(payload)
    if "error" in body:
        raise DriveError(str(body["error"].get("message", "listing refused")))
    if "files" not in body:
        raise DriveError("listing returned no `files` key")
    return dict(body)


def enumerate_tree(folder_id: str, key: str, *, on_folder: Any = None) -> list[dict[str, Any]]:
    """Every file under the folder, depth-first, with its path.

    Breadth is bounded by the tree, not by a page size: a folder listing that stopped at
    the first page would silently omit files, and a corpus missing documents nobody named
    is exactly the failure this system exists to prevent.
    """
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    stack: list[tuple[str, str]] = [(folder_id, "")]
    while stack:
        current, prefix = stack.pop()
        if current in seen:
            # Drive lets one folder sit in two parents; without this the walk never ends.
            continue
        seen.add(current)
        if on_folder is not None:
            on_folder(prefix or "/", len(files))
        token: str | None = None
        while True:
            page = _list_page(current, key, token)
            for entry in page.get("files", []):
                name = _safe_name(str(entry.get("name", "")))
                if entry.get("mimeType") == FOLDER_MIME:
                    stack.append((str(entry["id"]), f"{prefix}{name}/"))
                    continue
                files.append({**entry, "path": f"{prefix}{name}"})
            token = page.get("nextPageToken")
            if not token:
                break
    return files


#: ext4 and every other common filesystem cap one path component at 255 *bytes*, and a
#: Ukrainian title spends two bytes per character. A whole run died on one 300-byte
#: filename with no snapshot written, which is the wrong failure twice over: the name is
#: not the document, and one unwritable file is not a reason to lose the other 1745.
_MAX_COMPONENT_BYTES = 180


def _safe_name(name: str) -> str:
    """Keep the Drive name; shorten only what a filesystem cannot hold, traceably."""
    cleaned = name.replace("/", "∕").replace("\x00", "").strip()
    if cleaned in {"", ".", ".."}:
        return "unnamed"
    if len(cleaned.encode("utf-8")) <= _MAX_COMPONENT_BYTES:
        return cleaned
    # Truncated names collide — two manuals in one folder can share their first 150
    # characters. The digest is of the *full* Drive name, so the shortened name stays
    # unique and the original is still recoverable from the snapshot record.
    suffix = Path(cleaned).suffix[:16]
    marker = "~" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8]
    budget = _MAX_COMPONENT_BYTES - len((marker + suffix).encode("utf-8"))
    stem = Path(cleaned).stem.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return f"{stem}{marker}{suffix}"


def _download_url(entry: dict[str, Any]) -> tuple[str, str]:
    mime = str(entry.get("mimeType", ""))
    identifier = str(entry["id"])
    if mime in EXPORTS:
        target, suffix = EXPORTS[mime]
        return (
            "https://www.googleapis.com/drive/v3/files/"
            f"{identifier}/export?{urllib.parse.urlencode({'mimeType': target})}",
            suffix,
        )
    return (
        "https://drive.google.com/uc?"
        + urllib.parse.urlencode({"export": "download", "id": identifier, "confirm": "t"}),
        "",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_previous(destination: Path) -> dict[str, dict[str, Any]]:
    path = destination / "snapshot.json"
    if not path.is_file():
        return {}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(r["path"]): r for r in stored.get("records", []) if r.get("path")}


def _count_by_extension(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        mime = str(entry.get("mimeType", ""))
        suffix = EXPORTS[mime][1] if mime in EXPORTS else Path(str(entry["path"])).suffix.casefold()
        counts[suffix or "<none>"] = counts.get(suffix or "<none>", 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def _describe(entry: dict[str, Any]) -> dict[str, Any]:
    """What Drive said about this file, before anything is attempted with it."""
    mime = str(entry.get("mimeType", ""))
    relative = str(entry["path"])
    suffix = EXPORTS[mime][1] if mime in EXPORTS else Path(relative).suffix.casefold()
    if mime in EXPORTS:
        relative = f"{relative}{suffix}"
    return {
        "path": relative,
        "suffix": suffix,
        "drive_name": str(entry.get("name", "")),
        "drive_id": str(entry.get("id", "")),
        "drive_modified": str(entry.get("modifiedTime", "")),
        "drive_md5": str(entry.get("md5Checksum") or ""),
        "mime_type": mime,
        "ingestible": suffix in INGESTIBLE,
    }


def _refusal(
    record: dict[str, Any],
    entry: dict[str, Any],
    destination: Path,
    before: dict[str, Any] | None,
    arguments: argparse.Namespace,
    downloaded: int,
) -> dict[str, Any] | None:
    """Why this file is not being fetched, or None if it is. Every branch is named."""
    if not record["ingestible"]:
        return {"state": "NOT_INGESTIBLE"}
    declared = int(entry.get("size") or 0)
    if declared > arguments.max_file_bytes:
        return {"state": "REFUSED_TOO_LARGE", "bytes": declared}
    have_bytes = before is not None and before.get("drive_md5") == record["drive_md5"]
    if have_bytes and (destination / str(record["path"])).is_file():
        # Already have these exact bytes. Re-downloading them would spend an anonymous
        # quota that is shared with everything else this run still needs.
        assert before is not None
        return {
            "bytes": before.get("bytes"),
            "sha256": before.get("sha256"),
            "state": "UNCHANGED",
        }
    if arguments.limit and downloaded >= arguments.limit:
        return {"state": "NOT_FETCHED_LIMIT"}
    return None


def _fetch(entry: dict[str, Any], local: Path, suffix: str) -> dict[str, Any]:
    """The bytes, or the reason there are none. A record without `sha256` did not land."""
    url, _ = _download_url(entry)
    local.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = _request(url)
    except DriveError as error:
        return {"state": "FETCH_FAILED", "reason": str(error)[:200]}
    if payload[:15].lstrip().startswith(b"<!DOCTYPE html") and suffix != ".html":
        # Drive answers a refusal with an HTML interstitial and HTTP 200. Writing that to
        # disk as a .pdf is how a corpus acquires documents that are not documents.
        return {"state": "FETCH_REFUSED_INTERSTITIAL"}
    try:
        local.write_bytes(payload)
    except OSError as error:
        # One file the filesystem will not hold is not a reason to lose the run and the
        # snapshot with it. Named here, counted in `failed`, retried by re-running.
        return {"state": "WRITE_FAILED", "reason": f"{type(error).__name__}: {error}"[:200]}
    return {"bytes": local.stat().st_size, "sha256": _sha256(local)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder-id", required=True)
    parser.add_argument("--into", type=Path, required=True)
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument(
        "--limit", type=int, default=0, help="stop after N downloads; 0 means all of them"
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=_MAX_FILE_BYTES,
        help=(
            "Refuse any single file above this. Lowering it is how a first tranche is "
            "taken: the run is resumable, so raising it later fetches only what was "
            "refused, and every refusal is named in the snapshot rather than dropped."
        ),
    )
    parser.add_argument("--api-key", help="skip discovery and use this browser key")
    arguments = parser.parse_args()

    key = arguments.api_key or discover_api_key(arguments.folder_id)
    entries = enumerate_tree(
        arguments.folder_id,
        key,
        on_folder=(
            None
            if arguments.list_only
            else lambda path, seen: print(f"  {seen:>5} files · {path}", file=sys.stderr)
        ),
    )

    if arguments.list_only:
        print(
            json.dumps(
                {
                    "files": len(entries),
                    "by_extension": _count_by_extension(entries),
                    "bytes": sum(int(e.get("size") or 0) for e in entries),
                    "sample": [e["path"] for e in entries[:20]],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    destination = arguments.into
    destination.mkdir(parents=True, exist_ok=True)
    previous = _load_previous(destination)

    records: list[dict[str, Any]] = []
    changed: list[str] = []
    downloaded = 0
    for entry in entries:
        record = _describe(entry)
        relative = str(record["path"])
        before = previous.get(relative)
        blocked = _refusal(record, entry, destination, before, arguments, downloaded)
        if blocked is not None:
            records.append(record | blocked)
            continue
        outcome = _fetch(entry, destination / relative, str(record["suffix"]))
        records.append(record | outcome)
        if "sha256" not in outcome:
            continue
        downloaded += 1
        if before is not None and before.get("sha256") != outcome["sha256"]:
            records[-1]["state"] = "CHANGED"
            changed.append(relative)
        else:
            records[-1]["state"] = "UNCHANGED" if before is not None else "NEW"
        if downloaded % 25 == 0:
            print(f"  {downloaded} downloaded", file=sys.stderr)

    snapshot = {
        "schema_version": 1,
        "taken_at": datetime.now(UTC).isoformat(),
        "source": "google-drive-public-link",
        "folder_id": arguments.folder_id,
        "files": len(records),
        "ingestible": sum(1 for record in records if record.get("ingestible")),
        "downloaded_this_run": downloaded,
        "failed": sorted(
            str(r["path"])
            for r in records
            if str(r.get("state", "")).startswith(("FETCH_", "WRITE_"))
        ),
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
    for record in records:
        # A working field, not provenance. Kept out of the file so nothing downstream
        # starts treating a derived extension as something Drive reported.
        record.pop("suffix", None)
    (destination / "snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in snapshot.items() if k != "records"}, ensure_ascii=False, indent=2
        )
    )
    return 1 if changed or snapshot["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
