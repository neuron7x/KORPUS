"""Refuse unauthenticated runtime evidence before ZIP extraction."""

from __future__ import annotations

import zipfile


def opaque_runtime_failures(zf: zipfile.ZipFile) -> list[str]:
    names = [info.filename for info in zf.infolist()]
    roots = {name.split("/", 1)[0] for name in names}
    prefixes = ("",)
    if len(roots) == 1:
        prefixes += (f"{next(iter(roots))}/",)
    return [
        f"unverified runtime evidence forbidden: {name!r}"
        for name in names
        if any(
            name == f"{prefix}evidence" or name.startswith(f"{prefix}evidence/")
            for prefix in prefixes
        )
    ]
