"""Freeze and validate the exact boundary rows whose answers will be counted."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation_json import (
    MAX_METADATA_BYTES,
    MAX_SET_BYTES,
    is_digest,
    jsonl_rows,
    read_bounded,
    strict_json,
    string_list,
    text,
)
from reference_eval_set import reference_date

EXPECTATIONS = {"in_corpus": "answer", "out_of_corpus": "withhold"}


def _validate_rows(rows: list[dict[str, Any]]) -> None:
    ids: set[str] = set()
    for row in rows:
        if set(row) != {"id", "query", "stratum", "expect"}:
            raise ValueError("boundary case fields do not match the frozen schema")
        identifier = text(row["id"], "case id", 200)
        if identifier in ids:
            raise ValueError("duplicate boundary case id")
        ids.add(identifier)
        if len(text(row["query"], "query", 4000).strip()) < 3:
            raise ValueError("boundary query is too short")
        stratum = text(row["stratum"], "stratum", 100)
        if stratum not in EXPECTATIONS or row["expect"] != EXPECTATIONS[stratum]:
            raise ValueError("boundary stratum or expectation is invalid")


def load_boundary_set(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    body = read_bounded(path, MAX_SET_BYTES)
    rows = jsonl_rows(body)
    _validate_rows(rows)
    meta = strict_json(read_bounded(path.with_suffix(".meta.json"), MAX_METADATA_BYTES))
    if not isinstance(meta, dict) or meta.get("schema") != "korpus.domain-boundary-set.v1":
        raise ValueError("invalid boundary metadata schema")
    digest = hashlib.sha256(body).hexdigest()
    if not is_digest(meta.get("digest")) or meta["digest"] != digest:
        raise ValueError("boundary set digest does not match executed cases")
    actual = {"cases": len(rows), **Counter(row["stratum"] for row in rows)}
    for key in ("cases", *EXPECTATIONS):
        if type(meta.get(key)) is not int or meta[key] <= 0 or meta[key] != actual.get(key):
            raise ValueError("boundary metadata count differs from executed set")
    reference_date(meta.get("frozen_at"))
    string_list(meta.get("cannot_judge"), "measurement limits")
    return {**meta, "digest": digest}, rows
