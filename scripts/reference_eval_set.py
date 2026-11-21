"""Validate the actual frozen reference set before contacting a deployment."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from evaluation_json import (
    MAX_METADATA_BYTES,
    MAX_SET_BYTES,
    canonical_digest,
    is_digest,
    jsonl_rows,
    read_bounded,
    strict_json,
    string_list,
    text,
)

COMMON_FIELDS = {"id", "kind", "stratum", "query", "expect", "as_of", "note"}
EXTRA_FIELDS = {
    "retrieval": {
        "must_cite_one_of_if_answered",
        "sampled_from_version",
        "source_title",
        "evidence_sentence",
    },
    "refusal": set(),
    "adversarial": {"must_not_claim_binding"},
}
EXPECTATIONS = {
    "retrieval": {"answered_or_abstained"},
    "refusal": {"abstained"},
    "adversarial": {"abstained", "blocked_or_abstained", "answered_or_abstained"},
}


def reference_date(value: object) -> str:
    raw = text(value, "as_of", 10)
    if date.fromisoformat(raw).isoformat() != raw:
        raise ValueError("evaluation as_of must be an ISO calendar date")
    return raw


def validate_case(case: dict[str, Any]) -> None:
    for field in ("id", "kind", "stratum", "query", "expect"):
        text(case.get(field), field, 4000 if field == "query" else 200)
    kind = case["kind"]
    if kind not in EXTRA_FIELDS or set(case) - COMMON_FIELDS - EXTRA_FIELDS[kind]:
        raise ValueError("unknown reference case kind or field")
    if case["expect"] not in EXPECTATIONS[kind]:
        raise ValueError("reference case expectation does not match its kind")
    if len(case["query"].strip()) < 3:
        raise ValueError("reference query is too short")
    if "as_of" in case:
        reference_date(case["as_of"])
    for field in ("note", "source_title", "evidence_sentence", "sampled_from_version"):
        if field in case:
            text(case[field], field)
    if kind == "retrieval":
        _retrieval_case(case)
    if "must_not_claim_binding" in case and type(case["must_not_claim_binding"]) is not bool:
        raise ValueError("authority expectation must be boolean")


def _retrieval_case(case: dict[str, Any]) -> None:
    holders = string_list(case.get("must_cite_one_of_if_answered"), "expected versions")
    if any(str(UUID(holder)) != holder for holder in holders):
        raise ValueError("expected versions must be canonical UUID strings")
    for field in ("sampled_from_version", "source_title", "evidence_sentence"):
        text(case.get(field), field)
    if case["sampled_from_version"] not in holders:
        raise ValueError("sampled version is not an expected evidence holder")


def validate_metadata(meta: object, cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(meta, dict) or type(meta.get("schema_version")) is not int:
        raise ValueError("invalid reference metadata schema")
    if meta["schema_version"] != 1:
        raise ValueError("unsupported reference metadata schema")
    if type(meta.get("cases")) is not int or meta["cases"] != len(cases):
        raise ValueError("reference metadata case count differs from executed set")
    frozen_at = datetime.fromisoformat(text(meta.get("frozen_at"), "frozen_at", 100))
    if frozen_at.utcoffset() is None:
        raise ValueError("reference freeze time must include a timezone")
    string_list(meta.get("cannot_judge"), "measurement limits")
    if not is_digest(meta.get("content_digest")):
        raise ValueError("invalid reference set digest")
    digest = canonical_digest(cases)
    if digest != meta["content_digest"]:
        raise ValueError("reference set digest does not match executed cases")
    _metadata_counts(meta, cases)
    return {**meta, "content_digest": digest}


def _metadata_counts(meta: dict[str, Any], cases: list[dict[str, Any]]) -> None:
    if "strata" in meta and (
        type(meta["strata"]) is not int or meta["strata"] != len({c["stratum"] for c in cases})
    ):
        raise ValueError("reference metadata stratum count mismatch")
    if "by_kind" not in meta:
        return
    actual = Counter(case["kind"] for case in cases)
    stated = meta["by_kind"]
    if not isinstance(stated, dict) or set(stated) - set(EXPECTATIONS):
        raise ValueError("invalid reference metadata kinds")
    if any(type(value) is not int or value < 0 for value in stated.values()):
        raise ValueError("invalid reference metadata kind counts")
    if {key: value for key, value in stated.items() if value} != dict(actual):
        raise ValueError("reference metadata kind counts mismatch")


def load_reference_set(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases = jsonl_rows(read_bounded(path, MAX_SET_BYTES))
    for case in cases:
        validate_case(case)
    ids = [case["id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate reference case id")
    meta = strict_json(read_bounded(path.with_suffix(".meta.json"), MAX_METADATA_BYTES))
    return validate_metadata(meta, cases), cases
