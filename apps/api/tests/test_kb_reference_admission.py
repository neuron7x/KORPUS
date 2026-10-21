"""Negative controls for the separate KORPUS KB metadata-only research stage."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.kb_reference_admission import DEFAULT_CATALOG, _public_https_url, verify_catalog


def _rows() -> list[dict[str, object]]:
    return [json.loads(line) for line in DEFAULT_CATALOG.read_text(encoding="utf-8").splitlines()]


def _gate(tmp_path: Path, rows: list[dict[str, object]]) -> dict[str, object]:
    catalog = tmp_path / "catalog.jsonl"
    catalog.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return verify_catalog(catalog)


def test_original_foundation_sources_remain_metadata_only() -> None:
    result = verify_catalog()
    assert result["structure_status"] == "PASS"
    assert result["source_records"] == 18
    assert result["candidate_status"] == "BLOCKED"
    assert result["indexable"] == result["acquired"] == result["reviewed"] == 0
    assert result["production_authorized"] is False
    assert result["network_access_performed"] is False


@pytest.mark.parametrize("url", [
    "http://example.org/", "https://127.0.0.1/", "https://[::1]/",
    "https://example.org:8443/", "https://user:pass@example.org/",
    "https://example.org/?token=opaque", "https://localhost/",
    "https://host.local/", "https://example.org./", "https://example..org/",
    "https://example.org/#fragment", "https://example.org\\@evil.org/",
])
def test_unsafe_catalog_urls_are_refused(url: str) -> None:
    assert _public_https_url(url) is False


@pytest.mark.parametrize("field,value", [
    ("reuse_status", "APPROVED"),
    ("integration_mode", "INDEXABLE"),
    ("access_model", "AUTHORIZED"),
    ("category_ids", ["T00_OFFENSIVE_TACTICS"]),
    ("category_ids", []),
    ("url", "https://127.0.0.1/"),
    ("source_id", "SRC_BAD/../"),
])
def test_privilege_escalation_or_out_of_scope_field_blocks(
    tmp_path: Path, field: str, value: object
) -> None:
    rows = _rows()
    rows[0][field] = value
    result = _gate(tmp_path, rows)
    assert result["structure_status"] == "FAIL"
    assert result["production_authorized"] is False
    assert result["indexable"] == 0


def test_unknown_extra_authorization_field_is_refused(tmp_path: Path) -> None:
    rows = _rows()
    rows[0]["production_authorized"] = True
    assert _gate(tmp_path, rows)["structure_status"] == "FAIL"


def test_duplicate_ids_and_urls_are_refused(tmp_path: Path) -> None:
    rows = _rows()
    rows.append(rows[0].copy())
    assert "duplicate" in str(_gate(tmp_path, rows)["errors"])


def test_duplicate_json_fields_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "catalog.jsonl"
    path.write_text('{"a":1,"a":2}\n', encoding="utf-8")
    assert verify_catalog(path)["structure_status"] == "FAIL"


def test_empty_catalog_and_symlink_are_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert verify_catalog(empty)["structure_status"] == "FAIL"
    link = tmp_path / "link.jsonl"
    link.symlink_to(DEFAULT_CATALOG)
    assert verify_catalog(link)["structure_status"] == "FAIL"


def test_oversized_catalog_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "large.jsonl"
    path.write_bytes(b" " * (128 * 1024 + 1))
    assert verify_catalog(path)["structure_status"] == "FAIL"


def test_nonfinite_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"a": NaN}\n', encoding="utf-8")
    assert verify_catalog(path)["structure_status"] == "FAIL"
