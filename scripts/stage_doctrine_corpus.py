#!/usr/bin/env python3
"""Turn the doctrine catalog into a corpus the system can actually answer from.

The catalog is a bibliography: 84 curated sources with provenance, rights and a URI each.
Nothing in it is corpus bytes, so a system holding it can say which act governs a question
and not a word of what the act says. `import_corpus.py` takes a directory plus a sidecar
manifest; nothing connected the two, so the corpus stayed the one demonstration order
`bootstrap_local.py` seeds.

This fetches every ingestible source at the URI the content probe measured as richest,
writes the bytes to a staging directory, and emits the import manifest with metadata taken
from the catalog entry rather than invented from a filename.

Three things it deliberately does not do.

It does not approve. Every version import_corpus creates lands in quarantine; approval is a
person taking responsibility for a document entering the answerable set, under their name,
in the audit chain.

It does not stage a source the catalog blocks. `ingestible=false` means RESTRICTED
classification or unclear rights, and both are decisions somebody made on purpose.

It does not invent dates — it reads them. `effective_from` decides whether an answer cites
the version in force, so a guess there is a citation wrong in a way the reader cannot see.
But zakon.rada prints the revision date on the page being downloaded ("Редакція від
18.03.2026"), and reading it off the bytes already fetched is a measurement, not a guess.
Where the page does not say, the field stays absent.

That matters more than it looks. `ingestion.py:356` refuses to approve a version with
neither effective_from nor publication_date, and `import_corpus.py` does not ask for either:
all 90 documents imported cleanly and every one of them was permanently unapprovable —
quarantined by a rule the importer never mentioned. The two checks did not agree, and the
one that accepts did not ask about what the one that approves requires.

Every staged file is put through the system's own extractor before it is written into the
manifest. A download that returns 200 is not a document: on the first full run one source
served JavaScript under an HTML URL, and one PDF was four pages over the extractor's page
ceiling. Both would have been imported, failed at ingest time, and left the corpus quietly
short of two sources. Refusing here names them while there is still something to decide.

    stage_doctrine_corpus.py --out var/doctrine-staging
    stage_doctrine_corpus.py --out var/doctrine-staging --limit 5   # a sample first
    stage_doctrine_corpus.py --min-words 300      # what counts as a document
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
TAG = re.compile(r"<[^>]+>")
#: How zakon.rada prints the revision in force on the page it serves.
REVISION_DATE = re.compile(r"Редакц[іi][яi]\s+в[іi]д\s+(\d{2})\.(\d{2})\.(\d{4})")
MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def _fetch(uri: str, timeout: int) -> bytes:
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "-L",
            "--compressed",
            "--fail",
            "--max-time",
            str(timeout),
            "-A",
            "Mozilla/5.0 (KORPUS corpus staging)",
            "-e",
            "https://zakon.rada.gov.ua/",
            uri,
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl exit {result.returncode} on {uri}")
    return result.stdout


def _suffix_for(uri: str, payload: bytes) -> str:
    """The extension the extractor will dispatch on, decided by content, not by URL.

    zakon.rada serves an act at a path with no extension. Naming the file .html because the
    URL looked like a page is how a PDF ends up parsed as text.
    """
    if payload.startswith(b"%PDF-"):
        return ".pdf"
    if payload.startswith(b"PK\x03\x04"):
        return ".docx"
    lowered = uri.lower()
    for suffix in (".pdf", ".docx", ".json", ".txt", ".md"):
        if lowered.endswith(suffix):
            return suffix
    return ".html"


def _extractable(path: Path, min_words: int) -> tuple[bool, str]:
    """Read it with the system's own extractor, not a guess about its Content-Type.

    Returns (admissible, reason). The extractor is the authority: if ingestion would refuse
    the file, staging has already learned that, and the reason is the one ingestion would
    have given hours later.
    """
    from korpus.infrastructure.extraction import extract_pages_from_path

    mime = MIME_BY_SUFFIX.get(path.suffix.lower(), "text/plain")
    try:
        pages, _mode = extract_pages_from_path(
            path, path.name, mime, ocr_enabled=False, ocr_languages="ukr"
        )
    except ValueError as exc:
        return False, f"extractor refused: {exc}"
    words = len("\n".join(page.text for page in pages).split())
    if words < min_words:
        return False, f"only {words} words extracted, below the floor of {min_words}"
    return True, f"{words} words"


def _revision_date(payload: bytes, suffix: str) -> str | None:
    """The revision date the source itself prints, or None.

    Read from the bytes already downloaded, so it is a property of what was fetched rather
    than of what the catalog remembers. Only HTML: a PDF states its date in a layout this
    cannot read without guessing, and guessing is the thing being avoided.
    """
    if suffix not in {".html", ".htm"}:
        return None
    text = TAG.sub(" ", payload.decode("utf-8", "replace"))
    match = REVISION_DATE.search(re.sub(r"\s+", " ", text))
    if match is None:
        return None
    day, month, year = match.groups()
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:  # pragma: no cover - a printed date that is not a date
        return None


def _entry_for(source: dict[str, Any], relative: str) -> dict[str, Any]:
    probe = source.get("content_probe")
    uri = str(probe["chosen_uri"]) if isinstance(probe, dict) else str(source["source_uri"])
    entry: dict[str, Any] = {
        "file": relative,
        "canonical_title": str(source["canonical_title"]),
        "issuer": str(source["issuer"]),
        # The catalog carries no version number: every source is staged as revision 1 and a
        # later revision is a later staging run, which is what the source hash keys on.
        "revision": "1",
        "jurisdiction": str(source.get("jurisdiction", "UA")),
        "document_type": str(source.get("document_type", "reference")),
        "authority": str(source["authority"]),
        "access_tier": source.get("access_tier", 0),
        "classification": str(source.get("classification", "public")),
        "source_uri": uri,
        "catalog_id": str(source["id"]),
    }
    return entry


def _reportable(path: Path) -> str:
    """Repository-relative when it is inside the tree, absolute when staging elsewhere."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def stage(out: Path, timeout: int, limit: int | None, min_words: int) -> dict[str, Any]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    # Канонічний запис групи, не кожен її член. Шість пар id у каталозі вказують на ОДИН
    # файл (ARM/LOG, CAM/ENG, SIG/EW): документ заводили двічі, під різними розділами.
    # Взяти обидва означає покласти ті самі байти в корпус двічі — і кожна копія займає
    # окреме місце у видачі, тобто дублікати їдять top-5 напряму.
    #
    # `ingestible` при цьому лишається TRUE в обох: воно означає «права й форма дозволяють
    # це взяти», і для перехресного розміщення це правда. Зняти його з неканонічного
    # означало б записати властивість НАШОГО конвеєра як факт про документ — та сама
    # підміна, через яку недосяжність хоста мало не стала грифом. Пропускає той, хто
    # збирає, а не той, хто описує.
    sources = [
        s
        for s in catalog["sources"]
        if s.get("ingestible")
        and s.get("source_uri")
        and str(s.get("canonical_id", s.get("id"))) == str(s.get("id"))
    ]
    if limit is not None:
        sources = sources[:limit]

    out.mkdir(parents=True, exist_ok=True)
    documents: list[dict[str, Any]] = []
    refused: list[str] = []
    undated: list[str] = []
    staged_bytes = 0
    dated = 0

    for source in sources:
        probe = source.get("content_probe")
        uri = str(probe["chosen_uri"]) if isinstance(probe, dict) else str(source["source_uri"])
        try:
            payload = _fetch(uri, timeout)
        except RuntimeError as exc:
            refused.append(f"{source['id']}: {exc}")
            continue
        if not payload:
            refused.append(f"{source['id']}: empty response from {uri}")
            continue
        relative = f"{source['id']}{_suffix_for(uri, payload)}"
        target = out / relative
        target.write_bytes(payload)
        admissible, reason = _extractable(target, min_words)
        if not admissible:
            target.unlink()
            refused.append(f"{source['id']}: {reason} ({uri})")
            continue
        staged_bytes += len(payload)
        entry = _entry_for(source, relative)
        in_force = _revision_date(payload, target.suffix.lower())
        if in_force is not None:
            entry["effective_from"] = in_force
            dated += 1
        else:
            undated.append(str(source["id"]))
        documents.append(entry)

    # Attachments the catalog captured are already in the tree with a verified digest; they
    # are staged from there rather than re-fetched, so the corpus and the catalog's own
    # integrity anchor cannot disagree about what the annex contains.
    for source in sources:
        for anchor in source.get("attachment_anchors", []):
            if not anchor.get("extractor_supports_format"):
                continue
            local = ROOT / str(anchor["path"])
            if not local.is_file():
                refused.append(f"{source['id']}: captured attachment missing {anchor['path']}")
                continue
            relative = f"{source['id']}__{local.name}"
            target = out / relative
            target.write_bytes(local.read_bytes())
            # An annex is a form or a table, not a document: the word floor does not apply.
            admissible, reason = _extractable(target, min_words=1)
            if not admissible:
                target.unlink()
                refused.append(f"{source['id']}: attachment {local.name} {reason}")
                continue
            staged_bytes += local.stat().st_size
            entry = _entry_for(source, relative)
            entry["canonical_title"] = f"{entry['canonical_title']} — {local.name}"
            entry["source_uri"] = str(anchor["uri"])
            documents.append(entry)

    manifest = {
        "schema": "korpus.corpus-import-manifest.v1",
        "corpus_id": "public",
        "generated_from": "config/corpus/doctrine_catalog_2026.json",
        "catalog_sha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
        "documents": documents,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "staged": len(documents),
        "dated": dated,
        # Named, not hidden: every one of these will import cleanly and can never be
        # approved, because ingestion.py refuses an approval with no date in force.
        "undated_and_therefore_unapprovable": undated,
        "refused": refused,
        "bytes": staged_bytes,
        "manifest": _reportable(out / "manifest.json"),
        "catalog_sources_ingestible": len(sources),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "var/doctrine-staging")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--min-words",
        type=int,
        default=300,
        help="a staged source yielding fewer words than this is a page, not a document",
    )
    arguments = parser.parse_args()

    report = stage(arguments.out, arguments.timeout, arguments.limit, arguments.min_words)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Refusals are reported, not fatal: one unreachable source should not discard the rest.
    # The count is the signal, and it is in the report the caller reads.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
