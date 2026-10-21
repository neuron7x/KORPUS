"""Offline ASCII URI admission and Unicode metadata compatibility controls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import kb_reference_admission as gate

RAW_PATHS = (
    "caf\u00e9",
    "cafe\u0301",
    "\u0416",
    "\u4e2d",
    "\U0001f600",
    "\u0080",
    "\u0085",
    "\u2028",
    "\ud800",
    "\udfff",
)


def _row(index: int, url: str) -> dict[str, object]:
    return {
        "source_id": f"SRC_ASCII_{index}",
        "title": "Synthetic reference",
        "publisher": "Synthetic publisher",
        "url": url,
        "category_ids": ["T07_DATA_PROVENANCE_AND_RIGHTS"],
        "access_model": "PUBLIC_LANDING",
        "reuse_status": "UNASSESSED",
        "integration_mode": "METADATA_ONLY",
    }


def _verify(tmp_path: Path, rows: list[dict[str, object]]) -> dict[str, object]:
    catalog = tmp_path / "catalog.jsonl"
    catalog.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    result = gate.verify_catalog(catalog)
    assert result["candidate_status"] == "BLOCKED"
    assert result["rights_cleared"] == result["acquired"] == result["reviewed"] == 0
    assert result["indexable"] == 0
    assert result["production_authorized"] is False
    assert result["network_access_performed"] is False
    return result


@pytest.mark.parametrize("path", RAW_PATHS)
def test_literal_non_ascii_url_codepoints_are_refused(path: str) -> None:
    assert gate._public_https_url("https://example.org/" + path) is False


@pytest.mark.parametrize(
    "path",
    [
        "caf%C3%A9",
        "caf%c3%a9",
        "cafe%CC%81",
        "%E4%B8%AD",
        "%F0%9F%98%80",
        "path%3F%23",
    ],
)
def test_ascii_percent_encoded_path_data_remains_admissible(path: str) -> None:
    assert gate._public_https_url("https://example.org/" + path) is True


@pytest.mark.parametrize(
    "literal,encoded",
    [
        ("caf\u00e9", "caf%C3%A9"),
        ("cafe\u0301", "cafe%CC%81"),
        ("\u4e2d", "%E4%B8%AD"),
    ],
)
def test_mixed_iri_uri_catalog_cannot_pass(tmp_path: Path, literal: str, encoded: str) -> None:
    rows = [_row(0, "https://example.org/" + literal), _row(1, "https://example.org/" + encoded)]
    result = _verify(tmp_path, rows)
    assert result["structure_status"] == "FAIL"
    assert result["source_records"] == 1
    assert result["errors"] == ["line 1: invalid metadata-only source record"]


@pytest.mark.parametrize("field", ["title", "publisher"])
def test_unicode_metadata_is_not_subject_to_url_ascii_policy(tmp_path: Path, field: str) -> None:
    row = _row(0, "https://example.org/caf%C3%A9")
    row[field] = "\u0414\u043e\u0432\u0456\u0434\u043d\u0438\u043a caf\u00e9 \u4e2d"
    result = _verify(tmp_path, [row])
    assert result["structure_status"] == "PASS"
    assert result["source_records"] == 1
    assert result["errors"] == []


@pytest.mark.parametrize(
    "url",
    [
        "https://xn--bcher-kva.example/caf%C3%A9",
        "https://EXAMPLE.org/~valid%20path",
    ],
)
def test_ascii_host_and_uri_spellings_remain_admissible(url: str) -> None:
    assert gate._public_https_url(url) is True
