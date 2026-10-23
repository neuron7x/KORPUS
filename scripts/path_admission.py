from __future__ import annotations

from pathlib import Path


def symlink_free(path: Path) -> bool:
    absolute = path.absolute()
    return not any(item.is_symlink() for item in (absolute, *absolute.parents))


def regular_file(path: Path) -> bool:
    return path.absolute().is_file() and symlink_free(path)


def replace_regular(path: Path, content: bytes) -> None:
    absolute = path.absolute()
    if not symlink_free(absolute):
        raise ValueError(f"refusing symlinked output: {path}")
    if absolute.exists():
        if not absolute.is_file():
            raise ValueError(f"refusing non-file output: {path}")
        absolute.unlink()
    try:
        with absolute.open("xb") as output:
            output.write(content)
    except FileExistsError as error:
        raise ValueError(f"output changed during publication: {path}") from error
