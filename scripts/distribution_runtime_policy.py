"""Reject unauthenticated runtime paths before ZIP extraction."""

from __future__ import annotations

import zipfile


def _opaque_path(name: str) -> bool:
    parts = name.casefold().strip("/").split("/")
    preceding = ["", *parts[:-1]]
    return any(
        (part == "evidence" and prior != "handoff") or (prior, part) == ("var", "releases")
        for prior, part in zip(preceding, parts, strict=True)
    )


def opaque_runtime_failures(zf: zipfile.ZipFile) -> list[str]:
    return [
        f"unverified runtime evidence forbidden: {info.filename!r}"
        for info in zf.infolist()
        if _opaque_path(info.filename)
    ]
