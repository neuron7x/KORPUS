#!/usr/bin/env python3
"""Draft an import manifest from a fetched directory, refusing to invent what it cannot read.

`import_corpus.py` takes metadata from a manifest and never from a filename, because a
filename convention is a schema nobody validates and the guess would decide the issuer,
the date a document takes force, and the classification of what a soldier is shown. That
rule stands. This writes the *draft* so a curator edits one file instead of typing four
hundred entries, and every field it could not determine carries the sentinel below rather
than a plausible default.

`import_corpus.py` refuses any entry still carrying it. That is the whole design: a
half-filled manifest fails loudly, and nothing enters the corpus described by a guess.

What is derived, and why only these:

  file             the path, which is a fact
  canonical_title  the filename without its extension and leading numbering — wrong in
                   detail, but it is a label, not an authority claim, and a curator
                   reading the list sees immediately which ones are wrong
  document_type    the top-level directory, which in a numbered library is the subject

What is never derived:

  issuer           who published it. Nothing in a filename says this.
  authority        whether the source may govern an answer at all.
  revision         which edition. "v2_final_FINAL" is not a revision.
  publication_date the date it took force.

With `--snapshot`, the fields Drive itself recorded are carried through instead of left
to a curator: the file id becomes a `source_uri` a reader can open, and the date the copy
was last modified becomes `effective_from` — the earliest date this system can show the
document existed. `publication_date` stays empty on purpose. Nobody established it, the
answer surface says so for every citation drawn from such a version, and `effective_from`
is a floor rather than a claim: the source can never be cited as governing a date before
the copy is known to have existed.

`--authority` sets the class for the whole batch, and the default is `analytical` on
purpose. A library of military literature is not a set of orders: ingested as
`official_ua` the system would present training material as a binding norm, which is the
single worst thing it could do with a corpus like this. `AuthorityClass` decides whether
a source may govern an answer, and that decision belongs to whoever knows what the
documents are.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: `import_corpus.py` refuses any entry that still carries this.
REVIEW_REQUIRED = "REVIEW_REQUIRED"

INGESTIBLE = {".txt", ".md", ".json", ".html", ".htm", ".pdf", ".docx"}

#: `01. Тактика`, `02 - Медицина`, `3_Звязок` — a numbered library names its subjects in
#: the directory. The number is ordering, not meaning, so it is stripped.
LEADING_ORDER = re.compile(r"^\s*\d{1,3}\s*[.)\-_]*\s*")

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _title_from(path: Path) -> str:
    stem = LEADING_ORDER.sub("", path.stem).strip()
    stem = re.sub(r"[_]+", " ", stem)
    stem = re.sub(r"\s{2,}", " ", stem).strip(" -–—")
    return stem or path.stem


def _document_type_from(relative: Path) -> str:
    parts = relative.parts
    if len(parts) < 2:
        return "reference"
    subject = LEADING_ORDER.sub("", parts[0]).strip()
    slug = re.sub(r"[^\w\-]+", "-", subject, flags=re.UNICODE).strip("-").casefold()
    return slug or "reference"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_records(root: Path) -> dict[str, dict[str, Any]]:
    """What the fetcher recorded, keyed by path. Absent is fine; invented is not."""
    path = root / "snapshot.json"
    if not path.is_file():
        return {}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(r["path"]): r for r in stored.get("records", []) if r.get("path")}


def _entry_for(
    path: Path,
    relative: Path,
    record: dict[str, Any] | None,
    arguments: argparse.Namespace,
) -> dict[str, Any]:
    """One manifest entry: derived where derivation is a fact, sentinel everywhere else."""
    entry: dict[str, Any] = {
        "file": relative.as_posix(),
        "source_sha256": _sha256_file(path),
        "canonical_title": _title_from(path),
        "issuer": arguments.issuer or REVIEW_REQUIRED,
        # Not derived from the filename: "v2_final_FINAL" is not a revision, and a wrong
        # one makes two editions of the same order look like one document.
        "revision": REVIEW_REQUIRED,
        "authority": arguments.authority,
        "document_type": _document_type_from(relative),
        "access_tier": arguments.access_tier,
        "classification": arguments.classification,
        "compartments": [],
        "data_owner_id": REVIEW_REQUIRED,
        "rights_reference": REVIEW_REQUIRED,
        "rights_status": REVIEW_REQUIRED,
        "releasability": REVIEW_REQUIRED,
        "retention_policy_id": REVIEW_REQUIRED,
        "access_policy_id": REVIEW_REQUIRED,
        # Left absent rather than guessed. A version with neither `publication_date` nor
        # `effective_from` cannot be approved — the domain refuses it, because it would
        # govern every past date.
        "publication_date": REVIEW_REQUIRED,
    }
    if record is None:
        return entry
    seen = str(record.get("drive_modified", ""))[:10]
    if _ISO_DATE.fullmatch(seen):
        # The copy, not the edition. Named as such in both fields it fills: the revision
        # reads "копія від <date>" so nobody mistakes it for an edition number, and
        # effective_from is a floor — the earliest date this system can show the document
        # existed at all.
        entry["revision"] = f"копія від {seen}"
        entry["effective_from"] = seen
        entry.pop("publication_date")
    if record.get("drive_id"):
        entry["source_uri"] = f"https://drive.google.com/file/d/{record['drive_id']}/view"
    if not arguments.issuer:
        # Recorded as not established, which is a fact, rather than left as the sentinel,
        # which would refuse the whole batch. `authority` is what caps what an
        # unattributed source may govern, and it is set for the batch.
        entry["issuer"] = "Не встановлено"
    return entry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="the fetched directory")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--corpus-id", default="public")
    parser.add_argument(
        "--authority",
        default="analytical",
        help=(
            "Source class for the whole batch. Default `analytical`: a library of "
            "military literature is not a set of orders, and ingesting it as official_ua "
            "would present training material as a binding norm."
        ),
    )
    parser.add_argument(
        "--issuer",
        help=(
            "Publisher for the whole batch, when one applies. Without it every entry "
            "carries REVIEW_REQUIRED and import_corpus.py refuses them."
        ),
    )
    parser.add_argument(
        "--from-snapshot",
        action="store_true",
        help=(
            "Carry through what Drive recorded: source_uri from the file id, and "
            "effective_from from the copy's modified date. publication_date stays empty."
        ),
    )
    parser.add_argument("--access-tier", type=int, default=0)
    parser.add_argument("--classification", default="public")
    arguments = parser.parse_args()

    root = arguments.root
    if not root.is_dir():
        print(json.dumps({"valid": False, "reason": f"no directory at {root}"}))
        return 2

    snapshot = _snapshot_records(root) if arguments.from_snapshot else {}
    if arguments.from_snapshot and not snapshot:
        print(json.dumps({"valid": False, "reason": f"no snapshot.json under {root}"}))
        return 2

    documents: list[dict[str, Any]] = []
    unreadable: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "snapshot.json":
            continue
        relative = path.relative_to(root)
        if path.suffix.casefold() not in INGESTIBLE:
            unreadable.append(relative.as_posix())
            continue
        documents.append(_entry_for(path, relative, snapshot.get(relative.as_posix()), arguments))

    manifest = {
        "corpus_id": arguments.corpus_id,
        "generated_from": str(root),
        "review_sentinel": REVIEW_REQUIRED,
        "note": (
            "Draft. Every REVIEW_REQUIRED must be replaced before import_corpus.py will "
            "accept the entry. Titles are derived from filenames and are labels, not "
            "authority claims — read the list and fix the ones that are wrong."
        ),
        "documents": documents,
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "valid": True,
                "documents": len(documents),
                "unreadable_formats": len(unreadable),
                "unreadable_sample": unreadable[:20],
                "fields_awaiting_review": sorted(
                    {
                        name
                        for document in documents
                        for name, value in document.items()
                        if value == REVIEW_REQUIRED
                    }
                ),
                "written": str(arguments.out),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
