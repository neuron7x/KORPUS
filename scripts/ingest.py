#!/usr/bin/env python3
"""Ingest a document into the corpus.

Nothing enters the corpus without a stated authority, access tier and review state.
The default review state is `quarantined`: a document is searchable only after a
reviewer approves it, and this tool will not approve on the operator's behalf.

    python3 scripts/ingest.py doc.md --title "Настанова X" --authority official_ua
    python3 scripts/ingest.py doc.md --title "Наказ Y" --review approved --tier reviewed
    python3 scripts/ingest.py --approve <version-uuid> --reviewer "Сержант Б."
    python3 scripts/ingest.py --supersede <version-uuid> --replacement <version-uuid>

Re-running the same file is safe: chunk identity is derived from content, so the
second run inserts nothing and says so. That is also why approval is `--approve` and
not a second import with a different flag: the second import would change nothing
while looking like it had.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.ingestion import (  # noqa: E402
    SourceDescriptor,
    chunk_document,
    content_hash,
    read_source,
)
from korpus.config import get_settings  # noqa: E402
from korpus.domain.models import AccessTier, AuthorityClass, ReviewState  # noqa: E402
from korpus.infrastructure.store import CorpusStore  # noqa: E402

OPEN_CORPUS = UUID("00000000-0000-4000-8000-000000000001")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, help=".txt or .md file to ingest")
    parser.add_argument("--title", help="document title as a reader would name it")
    parser.add_argument(
        "--authority",
        default=AuthorityClass.UNKNOWN.value,
        choices=[cls.value for cls in AuthorityClass],
    )
    parser.add_argument(
        "--tier", default=AccessTier.PUBLIC.value, choices=[t.value for t in AccessTier]
    )
    parser.add_argument(
        "--review",
        default=ReviewState.QUARANTINED.value,
        choices=[state.value for state in ReviewState],
        help="quarantined by default; approval is a reviewer's act, not an import flag",
    )
    parser.add_argument("--corpus", default=str(OPEN_CORPUS), help="corpus UUID")
    parser.add_argument("--revision", default=None)
    parser.add_argument("--source-uri", default=None)
    parser.add_argument("--store", type=Path, default=None, help="database path override")
    parser.add_argument(
        "--approve",
        type=UUID,
        default=None,
        help="version to release for citation (a reviewer's act, not an import flag)",
    )
    parser.add_argument("--reviewer", default=None, help="who approves; required with --approve")
    parser.add_argument("--supersede", type=UUID, default=None, help="version to retire")
    parser.add_argument("--replacement", type=UUID, default=None, help="version that replaces it")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    # Whether --tier was typed matters for --approve: an unstated tier must leave the
    # existing one alone rather than silently resetting it to the flag's default.
    args.tier_given = any(arg.startswith("--tier") for arg in sys.argv[1:])
    store = CorpusStore(Path(args.store) if args.store else Path(get_settings().corpus_path))

    if args.approve:
        if not args.reviewer:
            print(
                "--approve requires --reviewer: an approval belongs to a person",
                file=sys.stderr,
            )
            return 2
        tier = AccessTier(args.tier) if args.tier_given else None
        released = store.approve(args.approve, args.reviewer, tier)
        store.record_audit(
            "corpus.approved",
            {
                "document_version_id": str(args.approve),
                "reviewer": args.reviewer,
                "chunks": released,
                "access_tier": tier.value if tier else "unchanged",
            },
        )
        print(
            json.dumps(
                {"approved_chunks": released, "reviewer": args.reviewer}, ensure_ascii=False
            )
        )
        if released == 0:
            print("жоден фрагмент не змінив стан — перевірте ідентифікатор версії", file=sys.stderr)
            return 1
        return 0

    if args.supersede:
        if not args.replacement:
            print("--supersede requires --replacement", file=sys.stderr)
            return 2
        retired = store.supersede(args.supersede, args.replacement)
        print(json.dumps({"superseded_chunks": retired}, ensure_ascii=False))
        return 0

    if not args.source or not args.title:
        print("a source file and --title are required", file=sys.stderr)
        return 2

    try:
        text = read_source(args.source)
    except (OSError, ValueError) as error:
        print(f"cannot read {args.source}: {error}", file=sys.stderr)
        return 2

    descriptor = SourceDescriptor(
        corpus_id=UUID(args.corpus),
        title=args.title,
        authority=AuthorityClass(args.authority),
        access_tier=AccessTier(args.tier),
        review_state=ReviewState(args.review),
        revision=args.revision,
        source_uri=args.source_uri or str(args.source),
    )
    spans = chunk_document(text, descriptor)
    if not spans:
        print(f"{args.source}: no paragraphs found — nothing ingested", file=sys.stderr)
        return 1

    digest = content_hash(text)
    inserted = sum(1 for span in spans if store.add(span, digest))
    report = {
        "file": str(args.source),
        "title": args.title,
        "document_id": str(spans[0].document_id),
        "document_version_id": str(spans[0].document_version_id),
        "content_sha256": digest,
        "chunks": len(spans),
        "inserted": inserted,
        "already_present": len(spans) - inserted,
        "review_state": descriptor.review_state.value,
        "access_tier": descriptor.access_tier.value,
        "authority": descriptor.authority.value,
        "corpus_id": str(descriptor.corpus_id),
        "searchable": descriptor.review_state is ReviewState.APPROVED,
    }
    store.record_audit("corpus.ingested", dict(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if descriptor.review_state is not ReviewState.APPROVED:
        print(
            "\nЦей документ НЕ буде цитуватися, доки рецензент не переведе його в "
            "стан approved.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
