"""Fail-closed schema for the parser subprocess IPC boundary."""
from __future__ import annotations

from typing import Any

from korpus.application.numeric_contracts import require_count

_STRING_FIELDS = ("path", "filename", "mime_type", "ocr_languages")


def parse_parser_request(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("parser request must be an object")
    result = dict(value)
    if not all(isinstance(result.get(name), str) and result[name] for name in _STRING_FIELDS):
        raise ValueError("parser request string fields must be non-empty strings")
    if not isinstance(result.get("ocr_enabled"), bool):
        raise ValueError("ocr_enabled must be a boolean")
    result["max_pdf_pages"] = require_count(
        result.get("max_pdf_pages"), positive=True, label="max_pdf_pages"
    )
    result["ocr_total_timeout_seconds"] = require_count(
        result.get("ocr_total_timeout_seconds"), positive=True,
        label="ocr_total_timeout_seconds",
    )
    return result
