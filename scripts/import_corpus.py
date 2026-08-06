#!/usr/bin/env python3
"""Bring a directory of documents into the corpus, one file at a time, refusals named.

The corpus was a fixture: one demonstration order, ingested by `bootstrap_local.py`.
Everything downstream — retrieval, calibration, the answer policy — is exercised against
that one document, so the system reads as a demonstration no matter how the interface
looks. This is what turns it into a corpus.

What it does not do is approve anything. Every version lands in quarantine, which is
where a reviewer finds it. Approval is a person taking responsibility for a document
entering the answerable set, it enters the audit chain under their name, and a bulk
importer that granted it would be forging that signature at scale. `--approve-as` exists
for a demonstration corpus and says exactly what it is in the audit note.

Metadata comes from a sidecar manifest rather than from filenames. A filename convention
is a schema nobody validates: `nakaz_12_2024_v2_final_FINAL.pdf` has to be parsed by
guesswork, and the guess decides the issuer, the date a document takes force and the
classification of what a soldier is shown. The manifest is explicit, it is read once,
and a file it does not describe is skipped with its name printed rather than ingested
under invented metadata.

Manifest (JSON):

    {
      "corpus_id": "public",
      "documents": [
        {
          "file": "orders/nakaz-12.pdf",
          "canonical_title": "Наказ № 12 про ведення журналу",
          "issuer": "Генеральний штаб",
          "revision": "1",
          "publication_date": "2026-01-15",
          "authority": "official_ua",
          "document_type": "order",
          "access_tier": 0,
          "classification": "public",
          "compartments": [],
          "effective_from": "2026-02-01",
          "publication_identifier": "12/2026"
        }
      ]
    }

Idempotent by source hash: re-running over the same tree re-imports nothing, so an
interrupted run is resumed by running it again.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.ingestion import ExtractionSettings  # noqa: E402
from korpus.application.policy import PolicyEngine  # noqa: E402
from korpus.composition import build_ingestion_service  # noqa: E402
from korpus.config import get_settings  # noqa: E402
from korpus.domain.models import (  # noqa: E402
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentCreate,
    Identity,
    ReviewState,
    ReviewTransition,
    VersionCreate,
)
from korpus.infrastructure.runtime import create_object_store, create_repository  # noqa: E402

#: Read from the manifest, never inferred. A missing one is a refusal, not a default:
#: guessing an issuer or a classification is how a restricted document ends up public.
REQUIRED_FIELDS = ("file", "canonical_title", "issuer", "revision")

MIME_BY_SUFFIX = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass
class Outcome:
    ingested: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ingested": len(self.ingested),
            "duplicates": len(self.duplicates),
            "refused": len(self.refused),
            "skipped_files_not_in_manifest": len(self.skipped),
            "refusals": self.refused,
            "skipped": self.skipped[:50],
            "interpretation": (
                "Every version is quarantined. A quarantined version cannot be cited in "
                "an answer until a reviewer approves it, which is a person taking "
                "responsibility under their own name in the audit chain."
            ),
        }


def _document_from(entry: dict[str, Any], corpus_id: str) -> DocumentCreate:
    return DocumentCreate(
        canonical_title=str(entry["canonical_title"]),
        corpus_id=str(entry.get("corpus_id", corpus_id)),
        issuer=str(entry["issuer"]),
        jurisdiction=str(entry.get("jurisdiction", "UA")),
        document_type=str(entry.get("document_type", "reference")),
        access_tier=AccessTier.parse(entry.get("access_tier", 0)),
        classification=Classification(str(entry.get("classification", "public"))),
        compartments=frozenset(str(value) for value in entry.get("compartments", [])),
    )


def _version_from(entry: dict[str, Any]) -> VersionCreate:
    def as_date(key: str) -> date | None:
        value = entry.get(key)
        return date.fromisoformat(str(value)) if value else None

    return VersionCreate(
        revision=str(entry["revision"]),
        publication_identifier=(
            str(entry["publication_identifier"]) if entry.get("publication_identifier") else None
        ),
        source_uri=str(entry["source_uri"]) if entry.get("source_uri") else None,
        publication_date=as_date("publication_date"),
        effective_from=as_date("effective_from"),
        effective_until=as_date("effective_until"),
        authority=AuthorityClass(str(entry.get("authority", "unknown"))),
    )


def _mime_for(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in MIME_BY_SUFFIX:
        return MIME_BY_SUFFIX[suffix]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _base_from(manifest: dict[str, Any], manifest_path: Path) -> Path:
    """Where the manifest's paths start.

    The draft records the directory it was generated from, and honouring it is what
    stops the most expensive way to get this wrong: writing the manifest one level above
    the tree it describes. Every entry then refuses with "file does not exist" — four
    hundred identical lines that look like a broken download rather than a wrong base —
    while the same run reports every real document as "not in the manifest".
    """
    recorded = str(manifest.get("generated_from", ""))
    if recorded and Path(recorded).is_dir():
        return Path(recorded)
    return manifest_path.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, help="directory the manifest paths are relative to")
    parser.add_argument("--subject", default="importer")
    parser.add_argument(
        "--approve-as",
        help=(
            "Approve every ingested version as this subject. For a demonstration corpus "
            "only: approval is a person's signature in the audit chain and this forges "
            "it at scale. The audit note says so."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    manifest_path = arguments.manifest
    if not manifest_path.is_file():
        print(json.dumps({"valid": False, "reason": f"no manifest at {manifest_path}"}))
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = arguments.root or _base_from(manifest, manifest_path)
    corpus_id = str(manifest.get("corpus_id", "public"))
    entries = manifest.get("documents")
    if not isinstance(entries, list) or not entries:
        print(json.dumps({"valid": False, "reason": "manifest lists no documents"}))
        return 2

    outcome = Outcome()
    described = set()
    sentinel = str(manifest.get("review_sentinel", "REVIEW_REQUIRED"))
    for index, entry in enumerate(entries):
        # Recorded before any refusal: a file the manifest *describes* is not "missing
        # from the manifest", however the entry turns out. Listing it under both headings
        # made the refusal report accuse itself.
        if entry.get("file"):
            described.add(str(entry["file"]))
        # A draft manifest from `build_import_manifest.py` marks every field it could not
        # read rather than filling in a plausible default. Refusing them here is what
        # makes that honest: a half-filled manifest fails loudly, and nothing enters the
        # corpus described by a guess.
        unreviewed = sorted(
            name for name, value in entry.items() if isinstance(value, str) and value == sentinel
        )
        if unreviewed:
            outcome.refused.append(
                {
                    "file": str(entry.get("file", f"<entry {index}>")),
                    "reason": f"awaiting review: {unreviewed}",
                }
            )
            continue
        missing = [name for name in REQUIRED_FIELDS if not entry.get(name)]
        if missing:
            outcome.refused.append(
                {"file": str(entry.get("file", f"<entry {index}>")), "reason": f"missing {missing}"}
            )
            continue

    # Named before anything is ingested: a file sitting in the tree that the manifest
    # does not describe is the one most likely to be the document somebody meant to add.
    for path in sorted(base.rglob("*")):
        if path.is_file() and path.suffix.casefold() in MIME_BY_SUFFIX:
            relative = path.relative_to(base).as_posix()
            if relative not in described and path != manifest_path:
                outcome.skipped.append(relative)

    if arguments.dry_run:
        outcome.as_dict()
        print(json.dumps({**outcome.as_dict(), "dry_run": True}, ensure_ascii=False, indent=2))
        return 0

    settings = get_settings()
    policy = PolicyEngine()
    repository = create_repository(settings, policy)
    repository.initialize()
    service = build_ingestion_service(
        repository,
        create_object_store(settings),
        policy,
        ExtractionSettings(
            ocr_enabled=settings.ocr_enabled,
            ocr_languages=settings.ocr_languages,
            max_pdf_pages=settings.max_pdf_pages,
            max_spans_per_document=settings.max_spans_per_document,
            max_chunk_chars=settings.max_chunk_chars,
            chunk_overlap_chars=settings.chunk_overlap_chars,
        ),
    )
    actor = Identity(
        subject=arguments.subject,
        roles=frozenset({"admin", "curator", "reviewer"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({corpus_id}),
    )

    try:
        for entry in entries:
            relative = str(entry.get("file", ""))
            if not relative or any(item["file"] == relative for item in outcome.refused):
                continue
            path = base / relative
            if not path.is_file():
                outcome.refused.append({"file": relative, "reason": "file does not exist"})
                continue
            try:
                result = service.ingest(
                    actor,
                    _document_from(entry, corpus_id),
                    _version_from(entry),
                    path.name,
                    _mime_for(path),
                    path.read_bytes(),
                )
            except Exception as error:  # noqa: BLE001 — see below
                # Named per file, and the run continues. A batch that stops at the first
                # bad document tells an operator one thing about a hundred files.
                #
                # Deliberately broad, and the narrow tuple that used to be here is why:
                # it named the refusals the parser was *designed* to raise, so the first
                # library PDF whose page tree pypdf could not walk raised PdfReadError
                # instead and ended a 1740-document run at 918 — after five hours, with
                # no report written, because the report is printed at the end.
                #
                # The exception type is recorded, so a class of failure nobody predicted
                # is visible in the output as itself rather than as "refused".
                outcome.refused.append(
                    {"file": relative, "reason": f"{type(error).__name__}: {error}"[:300]}
                )
                continue
            if result.duplicate:
                outcome.duplicates.append(relative)
                continue
            outcome.ingested.append(relative)
            if arguments.approve_as:
                approver = Identity(
                    subject=arguments.approve_as,
                    roles=frozenset({"admin", "reviewer"}),
                    clearance=AccessTier.RESTRICTED,
                    corpora=frozenset({corpus_id}),
                )
                for state in (
                    ReviewState.METADATA_REVIEWED,
                    ReviewState.CONTENT_REVIEWED,
                    ReviewState.APPROVED,
                ):
                    service.transition(
                        approver,
                        result.version.id,
                        ReviewTransition(
                            target=state,
                            note=(
                                "bulk import approval: not an individual review of this "
                                "document, recorded as such"
                            ),
                            acknowledge_near_duplicate=True,
                            acknowledge_extraction_quality=True,
                        ),
                    )
    finally:
        repository.close()

    report = outcome.as_dict()
    absent = sum(1 for item in outcome.refused if item["reason"] == "file does not exist")
    if absent and absent == len(entries):
        # Not a corpus of missing files. A base that does not contain them.
        report["diagnosis"] = (
            f"every entry refused as missing under {base} — the manifest almost "
            "certainly describes a different directory; pass --root"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if outcome.refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
