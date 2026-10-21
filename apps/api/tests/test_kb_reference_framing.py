"""Offline JSONL framing and rejected-row resource-bound regression controls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts import kb_reference_admission as gate


def _row(index: int = 0) -> dict[str, object]:
    return {
        "source_id": f"SRC_CASE_{index:04d}",
        "title": "Synthetic reference",
        "publisher": "Synthetic publisher",
        "url": f"https://example.org/reference/{index}",
        "category_ids": ["T07_DATA_PROVENANCE_AND_RIGHTS"],
        "access_model": "PUBLIC_LANDING",
        "reuse_status": "UNASSESSED",
        "integration_mode": "METADATA_ONLY",
    }


def _verify(tmp_path: Path, text: str) -> dict[str, Any]:
    path = tmp_path / "catalog.jsonl"
    path.write_bytes(text.encode("utf-8"))
    result = gate.verify_catalog(path)
    assert result["candidate_status"] == "BLOCKED"
    assert result["rights_cleared"] == result["acquired"] == result["reviewed"] == 0
    assert result["indexable"] == 0
    assert result["production_authorized"] is False
    assert result["network_access_performed"] is False
    return result


@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\u2029"])
@pytest.mark.parametrize("field", ["title", "publisher"])
def test_unicode_inside_json_strings_is_not_a_record_boundary(
    tmp_path: Path, field: str, separator: str
) -> None:
    row = _row()
    row[field] = "before" + separator + "after"
    result = _verify(tmp_path, json.dumps(row, ensure_ascii=False) + "\n")
    assert result["structure_status"] == "PASS"
    assert result["source_records"] == 1
    assert result["errors"] == []


@pytest.mark.parametrize(
    "separator", ["\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]
)
def test_non_lf_separators_do_not_invent_jsonl_records(tmp_path: Path, separator: str) -> None:
    text = json.dumps(_row()) + separator + json.dumps(_row(1)) + "\n"
    result = _verify(tmp_path, text)
    assert result["structure_status"] == "FAIL"
    assert result["source_records"] == 0
    assert len(result["errors"]) == 2
    assert result["errors"][0].startswith("line 1: invalid JSON:")


@pytest.mark.parametrize("whitespace", ["\u00a0", "\u2003", "\v", "\f", "\x85", "\u2028", "\u2029"])
def test_non_json_whitespace_lines_are_not_silently_discarded(
    tmp_path: Path, whitespace: str
) -> None:
    result = _verify(tmp_path, json.dumps(_row()) + "\n" + whitespace + "\n")
    assert result["structure_status"] == "FAIL"
    assert result["source_records"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0].startswith("line 2: invalid JSON:")


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize("terminal", [False, True])
def test_lf_crlf_and_optional_final_newline_remain_valid(
    tmp_path: Path, ending: str, terminal: bool
) -> None:
    text = ending.join(json.dumps(_row(index)) for index in range(2))
    result = _verify(tmp_path, text + (ending if terminal else ""))
    assert result["structure_status"] == "PASS"
    assert result["source_records"] == 2
    assert result["errors"] == []


@pytest.mark.parametrize("invalid", ["{", "{}", "null", '{"a":NaN}', '{"a":1,"a":2}'])
def test_rejected_rows_consume_the_parser_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    monkeypatch.setattr(gate, "MAX_ROWS", 2)
    text = (invalid + "\n") * 5 + json.dumps(_row()) + "\n"
    with patch.object(gate.json, "loads", wraps=json.loads) as loads:
        result = _verify(tmp_path, text)
    assert loads.call_count == 2
    assert result["structure_status"] == "FAIL"
    assert result["source_records"] == 0
    assert len(result["errors"]) == 3
    assert result["errors"][-1] == "catalog row count exceeds bounded maximum"


@pytest.mark.parametrize("count", [1, 2, 3])
def test_valid_row_boundary_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    monkeypatch.setattr(gate, "MAX_ROWS", 2)
    text = "\n".join(json.dumps(_row(index)) for index in range(count)) + "\n"
    result = _verify(tmp_path, text)
    assert result["source_records"] == min(count, 2)
    assert result["structure_status"] == ("PASS" if count <= 2 else "FAIL")


def test_mixed_valid_and_rejected_rows_share_one_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "MAX_ROWS", 2)
    text = json.dumps(_row()) + "\n{}\n" + json.dumps(_row(1)) + "\n"
    result = _verify(tmp_path, text)
    assert result["structure_status"] == "FAIL"
    assert result["source_records"] == 1
    assert len(result["errors"]) == 2
    assert result["errors"][-1] == "catalog row count exceeds bounded maximum"


def test_existing_ascii_blank_line_tolerance_does_not_consume_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "MAX_ROWS", 2)
    text = "\n \t\r\n" + json.dumps(_row()) + "\n\t\n" + json.dumps(_row(1)) + "\n\n"
    result = _verify(tmp_path, text)
    assert result["structure_status"] == "PASS"
    assert result["source_records"] == 2


def test_default_rejected_row_diagnostics_are_bounded(tmp_path: Path) -> None:
    result = _verify(tmp_path, "{}\n" * (gate.MAX_ROWS + 1))
    assert result["structure_status"] == "FAIL"
    assert result["source_records"] == 0
    assert len(result["errors"]) == gate.MAX_ROWS + 1
    assert result["errors"][-1] == "catalog row count exceeds bounded maximum"
