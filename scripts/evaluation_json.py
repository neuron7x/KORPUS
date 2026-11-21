"""Strict, bounded JSON and identity primitives for evaluation inputs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

MAX_SET_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
MAX_CASES = 10_000


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise ValueError("non-finite JSON number")


def strict_json(body: str | bytes) -> Any:
    return json.loads(body, object_pairs_hook=_object, parse_constant=_nonfinite)


def read_bounded(path: Path, maximum: int) -> bytes:
    with path.open("rb") as handle:
        body = handle.read(maximum + 1)
    if len(body) > maximum:
        raise ValueError("evaluation input exceeds its size limit")
    return body


def canonical_digest(cases: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for case in cases:
        digest.update(
            json.dumps(case, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def is_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def text(value: object, field: str, maximum: int = 10_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"invalid evaluation {field}")
    if "\x00" in value:
        raise ValueError(f"NUL in evaluation {field}")
    return value


def string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > MAX_CASES:
        raise ValueError(f"invalid evaluation {field}")
    result = [text(item, field) for item in value]
    if len(set(result)) != len(result):
        raise ValueError(f"duplicate evaluation {field}")
    return result


def jsonl_rows(body: bytes) -> list[dict[str, Any]]:
    if len(body) > MAX_SET_BYTES:
        raise ValueError("evaluation set exceeds its size limit")
    rows = [strict_json(line) for line in body.decode("utf-8").splitlines() if line.strip()]
    if not rows or len(rows) > MAX_CASES or any(not isinstance(row, dict) for row in rows):
        raise ValueError("evaluation set must contain bounded nonempty object rows")
    return rows
