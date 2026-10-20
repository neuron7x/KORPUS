"""Reject opaque runtime paths while retaining verified report evidence."""

from __future__ import annotations

import zipfile


def _opaque_path(name: str) -> bool:
    parts = [part.rstrip(" .").casefold() for part in name.strip("/").split("/")]
    pairs = set(zip(parts, parts[1:], strict=False))
    trusted = (
        parts[0] == "reports"
        or parts[1:2] == ["reports"]
        or parts[:2] == ["handoff", "evidence"]
        or parts[1:3] == ["handoff", "evidence"]
    )
    return (
        ("var", "evidence") in pairs
        or ("var", "releases") in pairs
        or ("evidence" in parts and not trusted)
    )


def opaque_runtime_failures(zf: zipfile.ZipFile) -> list[str]:
    return [
        f"unverified runtime evidence forbidden: {info.filename!r}"
        for info in zf.infolist()
        if _opaque_path(info.filename)
    ]
