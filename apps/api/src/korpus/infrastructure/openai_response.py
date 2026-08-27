"""Fail-closed admission of a raw OpenAI Responses API envelope."""

from __future__ import annotations

from typing import Any


def _content(item: Any) -> list[Any]:
    value = item.get("content") if isinstance(item, dict) else None
    return value if isinstance(value, list) else []


def _text(block: Any) -> str:
    if not isinstance(block, dict) or block.get("type") not in {"output_text", "text"}:
        return ""
    value = block.get("text")
    return value if isinstance(value, str) else ""


def completed_response_text(body: Any) -> str:
    """Return text only from a completed, error-free Responses object."""
    if not isinstance(body, dict):
        return ""
    if body.get("status") != "completed" or body.get("error") is not None:
        return ""
    direct = body.get("output_text")
    if isinstance(direct, str):
        return direct.strip()
    output = body.get("output")
    if not isinstance(output, list):
        return ""
    chunks = (_text(block) for item in output for block in _content(item))
    return "".join(chunk for chunk in chunks if chunk).strip()
