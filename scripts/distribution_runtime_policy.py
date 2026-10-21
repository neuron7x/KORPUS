"""Reject opaque runtime paths while retaining verified report evidence."""

from __future__ import annotations

import zipfile
from itertools import pairwise


def _opaque_path(name: str) -> bool:
    parts = [part.rstrip(" .").casefold() for part in name.strip("/").split("/")]
    pairs = set(pairwise(parts))
    trusted = (
        ["reports", "release"] in [parts[:2], parts[1:3]]
        or parts[:2] == ["handoff", "evidence"]
        or parts[1:3] == ["handoff", "evidence"]
    )
    return (
        not all(parts)
        or ("var", "evidence") in pairs
        or ("var", "releases") in pairs
        or ("evidence" in parts and not trusted)
    )


def opaque_runtime_failures(zf: zipfile.ZipFile) -> list[str]:
    return [
        f"unverified runtime evidence forbidden: {info.filename!r}"
        for info in zf.infolist()
        if _opaque_path(info.filename)
    ]
