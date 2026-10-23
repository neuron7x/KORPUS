from __future__ import annotations

from pathlib import Path

from path_admission import replace_regular


def publish(path: Path, content: bytes) -> None:
    try:
        replace_regular(path, content)
    except ValueError as error:
        raise SystemExit(f"unsafe assurance destination: {path}") from error
