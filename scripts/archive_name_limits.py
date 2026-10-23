"""Conservative POSIX filesystem name ceilings; staging handles stricter hosts."""

from __future__ import annotations

_MAX_COMPONENT_BYTES = 255
_MAX_RELATIVE_PATH_BYTES = 4095


def name_length_failure(name: str) -> str | None:
    try:
        encoded = name.encode("utf-8")
        parts = [part.encode("utf-8") for part in name.removesuffix("/").split("/")]
    except UnicodeEncodeError:
        return f"unencodable ZIP entry name: {name!r}"
    if any(len(part) > _MAX_COMPONENT_BYTES for part in parts):
        return f"ZIP component exceeds {_MAX_COMPONENT_BYTES} UTF-8 bytes: {name!r}"
    if len(encoded) > _MAX_RELATIVE_PATH_BYTES:
        return f"ZIP path exceeds {_MAX_RELATIVE_PATH_BYTES} UTF-8 bytes: {name!r}"
    return None
