"""Offline URL-component controls for the metadata-only reference gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.kb_reference_admission import (
    _canonical_source_url,
    _public_https_url,
    verify_catalog,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org?",
        "https://example.org#",
        "https://example.org/?",
        "https://example.org/#",
        "https://example.org/path?",
        "https://example.org/path#",
        "https://example.org/path?#",
        "https://example.org/path?query",
        "https://example.org/path#fragment",
        "https://example.org/path%3F?",
        "https://example.org/path%23#",
    ],
)
def test_query_and_fragment_components_are_not_admitted(url: str) -> None:
    assert _public_https_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/path%3F",
        "https://example.org/path%3f",
        "https://example.org/path%23",
        "https://example.org/path%3F%23",
    ],
)
def test_encoded_delimiters_remain_path_data(url: str) -> None:
    assert _public_https_url(url) is True


@pytest.mark.parametrize("suffix", ["?", "#", "?#"])
def test_empty_component_is_rejected_by_catalog_gate(tmp_path: Path, suffix: str) -> None:
    row = {
        "source_id": "SRC_COMPONENT_BOUNDARY",
        "title": "Public reference",
        "publisher": "Example publisher",
        "url": "https://example.org/path" + suffix,
        "category_ids": ["T07_DATA_PROVENANCE_AND_RIGHTS"],
        "access_model": "PUBLIC_LANDING",
        "reuse_status": "UNASSESSED",
        "integration_mode": "METADATA_ONLY",
    }
    path = tmp_path / "catalog.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = verify_catalog(path)
    assert result["structure_status"] == "FAIL"
    assert result["source_records"] == 0
    assert any("invalid metadata-only source record" in error for error in result["errors"])
    assert result["candidate_status"] == "BLOCKED"
    assert result["indexable"] == result["acquired"] == result["rights_cleared"] == 0
    assert result["production_authorized"] is False
    assert result["network_access_performed"] is False


@pytest.mark.parametrize("suffix", ["%3F", "%23"])
def test_encoded_delimiters_keep_distinct_resource_keys(suffix: str) -> None:
    original = "https://example.org/path"
    assert _canonical_source_url(original + suffix) != _canonical_source_url(original)
