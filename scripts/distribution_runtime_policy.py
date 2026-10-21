from __future__ import annotations

import zipfile
from itertools import pairwise

from git_bundle_policy import bundle_zip_failures


def _opaque_path(name: str) -> bool:
    parts = [part.rstrip(" .").casefold() for part in name.strip("/").split("/")]
    before = parts[: [*parts, "evidence"].index("evidence")]
    trusted = (
        ["reports", "release"] in [before[:2], before[1:3]]
        or before == ["handoff"]
        or before[1:] == ["handoff"]
    )
    return (
        not all(parts)
        or ("var", "evidence") in pairwise(parts)
        or ("var", "releases") in pairwise(parts)
        or ("evidence" in parts and not trusted)
    )


def opaque_runtime_failures(zf: zipfile.ZipFile) -> list[str]:
    return [
        f"unverified runtime evidence forbidden: {info.filename!r}"
        for info in zf.infolist()
        if _opaque_path(info.filename)
    ] + bundle_zip_failures(zf)
