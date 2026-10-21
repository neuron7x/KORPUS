"""Offline RFC 3986 path-character admission and encoding regression controls."""

from __future__ import annotations

import json
import string
from pathlib import Path

import pytest

from scripts import kb_reference_admission as gate

PATH_CHARACTERS = frozenset(string.ascii_letters + string.digits + "-._~!$&'()*+,;=:@/")
EXCLUDED = tuple(chr(code) for code in (34, 60, 62, 91, 93, 94, 96, 123, 124, 125))


def _row(index: int, url: str) -> dict[str, object]:
    return {
        "source_id": f"SRC_GRAMMAR_{index}",
        "title": "Reference title",
        "publisher": "Reference publisher",
        "url": url,
        "category_ids": ["T07_DATA_PROVENANCE_AND_RIGHTS"],
        "access_model": "PUBLIC_LANDING",
        "reuse_status": "UNASSESSED",
        "integration_mode": "METADATA_ONLY",
    }


@pytest.mark.parametrize("code", range(128))
def test_every_literal_ascii_path_character(code: int) -> None:
    character = chr(code)
    actual = gate._public_https_url("https://example.org/a" + character + "b")
    assert actual is (character in PATH_CHARACTERS)


@pytest.mark.parametrize("character", (*EXCLUDED, chr(92), "?", "#"))
def test_encoded_excluded_characters_remain_path_data(character: str) -> None:
    encoded = f"%{ord(character):02X}"
    assert gate._public_https_url("https://example.org/a" + encoded + "b") is True


@pytest.mark.parametrize("suffix", ["%", "%0", "%GG", "a%2g", "a%20%"])
def test_malformed_percent_triplets_remain_rejected(suffix: str) -> None:
    assert gate._public_https_url("https://example.org/" + suffix) is False


@pytest.mark.parametrize("character", EXCLUDED)
def test_raw_and_encoded_spellings_cannot_both_enter_catalog(
    tmp_path: Path, character: str
) -> None:
    raw = "https://example.org/a" + character + "b"
    encoded = "https://example.org/a" + f"%{ord(character):02X}" + "b"
    path = tmp_path / "catalog.jsonl"
    text = "\n".join(json.dumps(_row(index, url)) for index, url in enumerate((raw, encoded)))
    path.write_text(text + "\n", encoding="utf-8")
    result = gate.verify_catalog(path)
    assert result["structure_status"] == "FAIL"
    assert result["source_records"] == 1
    assert any("invalid metadata-only source record" in error for error in result["errors"])
    assert result["candidate_status"] == "BLOCKED"
    assert result["acquired"] == result["indexable"] == result["rights_cleared"] == 0
    assert result["production_authorized"] is False
    assert result["network_access_performed"] is False


@pytest.mark.parametrize("path", ["", "/", "/a:b", "/a@b", "/a!$&'()*+,;=b", "/a//b", "/a%2Fb"])
def test_legal_path_shapes_remain_admissible(path: str) -> None:
    assert gate._public_https_url("https://example.org" + path) is True


def test_default_catalog_retains_metadata_only_result() -> None:
    result = gate.verify_catalog()
    assert result["structure_status"] == "PASS"
    assert result["source_records"] == 18
    assert result["candidate_status"] == "BLOCKED"
    assert result["indexable"] == result["acquired"] == 0
    assert result["production_authorized"] is False
    assert result["network_access_performed"] is False
