"""Neutral synthetic archive fixtures; no live corpus or deployment data."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

DOCUMENT = "00000000-0000-4000-8000-000000000001"
VERSION = "00000000-0000-4000-8000-000000000002"
SPAN = "00000000-0000-4000-8000-000000000003"
OTHER = "00000000-0000-4000-8000-000000000004"
DATE = "2026-06-01"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def case() -> dict[str, Any]:
    return {
        "id": "archive-01",
        "kind": "retrieval",
        "stratum": "archive",
        "query": "Which label is blue?",
        "expect": "answered_or_abstained",
        "must_cite_one_of_if_answered": [VERSION],
        "sampled_from_version": VERSION,
        "source_title": "Synthetic archive",
        "evidence_sentence": "Blue label on shelf four.",
    }


def evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    text = "Архівна картка. Blue label on shelf four. Final note."
    quote = "Blue label on shelf four."
    span = {
        "id": SPAN,
        "document_id": DOCUMENT,
        "version_id": VERSION,
        "document_title": "Synthetic archive",
        "revision": "1",
        "page": 1,
        "section": "Labels",
        "text": text,
        "text_hash": sha(text),
        "source_hash": sha("synthetic archive original bytes"),
        "source_uri": "https://archive.example.invalid/source",
    }
    citation = {
        "span_id": SPAN,
        "document_id": DOCUMENT,
        "version_id": VERSION,
        "title": span["document_title"],
        "revision": span["revision"],
        "page": span["page"],
        "section": span["section"],
        "quote": quote,
        "quote_start": text.index(quote),
        "quote_end": text.index(quote) + len(quote),
        "quote_hash": sha(quote),
        "span_hash": span["text_hash"],
        "source_hash": span["source_hash"],
        "source_uri": span["source_uri"],
    }
    return citation, span


def freeze_reference(path: Path, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = [case()] if rows is None else rows
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    meta = {
        "schema_version": 1,
        "frozen_at": "2026-06-01T00:00:00+00:00",
        "cases": len(rows),
        "by_kind": dict(Counter(row["kind"] for row in rows)),
        "strata": len({row["stratum"] for row in rows}),
        "content_digest": sha(body),
        "cannot_judge": ["Synthetic mechanical control, not semantic quality."],
    }
    path.write_text(body, encoding="utf-8")
    path.with_suffix(".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def freeze_boundary(path: Path) -> dict[str, Any]:
    rows = [
        {
            "id": "inside",
            "query": "Which archive label?",
            "stratum": "in_corpus",
            "expect": "answer",
        },
        {
            "id": "outside",
            "query": "Unrelated archive query?",
            "stratum": "out_of_corpus",
            "expect": "withhold",
        },
    ]
    body = "".join(json.dumps(row) + "\n" for row in rows)
    meta = {
        "schema": "korpus.domain-boundary-set.v1",
        "digest": sha(body),
        "frozen_at": "2026-06-01",
        "cases": 2,
        "in_corpus": 1,
        "out_of_corpus": 1,
        "cannot_judge": ["These counts do not measure answer correctness."],
    }
    path.write_text(body, encoding="utf-8")
    path.with_suffix(".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta
