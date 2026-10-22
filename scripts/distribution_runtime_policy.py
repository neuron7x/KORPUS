import zipfile
from itertools import pairwise

from git_bundle_policy import bundle_zip_failures


def _opaque_path(name: str) -> bool:
    parts = [part.rstrip(" .").casefold() for part in name.strip("/").split("/")]
    before = parts[: [*parts, "evidence"].index("evidence")]
    trusted = before[:2] == ["reports", "release"] or before == ["handoff"]
    runtime = {("var", "evidence"), ("var", "releases")} & set(pairwise(parts))
    return not all(parts) or bool(runtime) or ("evidence" in parts and not trusted)


def _root_alias_failures(roots: set[str]) -> list[str]:
    keys = [root.rstrip(" .").casefold() for root in roots]
    return ["archive root aliases forbidden"] if len(keys) != len(set(keys)) else []


def opaque_runtime_failures(zf: zipfile.ZipFile) -> list[str]:
    roots = set(map(lambda name: name.partition("/")[0], zf.namelist()))
    prefix = f"{next(iter(roots))}/" if len(roots) == 1 else ""
    failures = [
        f"unverified runtime evidence forbidden: {info.filename!r}"
        for info in zf.infolist()
        if _opaque_path(info.filename.removeprefix(prefix) or info.filename)
    ]
    return _root_alias_failures(roots) + failures + bundle_zip_failures(zf)
