"""Bounded OCR with explicit original page identities."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from korpus.domain.models import ExtractedPage
from korpus.infrastructure.pdf_page_evidence import remaining_time


def _render(
    path: Path, prefix: Path, first: int, last: int, deadline: float, *, single: bool = False
) -> None:
    command = ["pdftoppm", "-png", "-r", "220", "-f", str(first), "-l", str(last)]
    if single:
        command.append("-singlefile")
    subprocess.run(
        [*command, str(path), str(prefix)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=remaining_time(deadline),
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
    )


def _images(
    path: Path, root: Path, deadline: float, maximum: int, selected: tuple[int, ...] | None
) -> list[tuple[int, Path]]:
    if selected is None:
        _render(path, root / "page", 1, maximum, deadline)
        images = sorted(root.glob("page-*.png"))
        if len(images) > maximum:
            raise ValueError("OCR renderer exceeded page limit")
        return list(enumerate(images, start=1))
    if (
        not selected
        or tuple(sorted(set(selected))) != selected
        or any(type(page) is not int or not 1 <= page <= maximum for page in selected)
    ):
        raise ValueError("OCR page selection is invalid")
    result: list[tuple[int, Path]] = []
    for page in selected:
        prefix = root / f"page-{page}"
        _render(path, prefix, page, page, deadline, single=True)
        result.append((page, prefix.with_suffix(".png")))
    if set(root.glob("*.png")) != {image for _page, image in result}:
        raise ValueError("OCR renderer returned an incomplete page inventory")
    return result


def ocr_pages(
    path: Path,
    languages: str,
    deadline: float,
    max_pages: int,
    normalize: Callable[[str], str],
    *,
    page_numbers: tuple[int, ...] | None = None,
) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    with tempfile.TemporaryDirectory(prefix="korpus-ocr-") as directory:
        for page, image in _images(path, Path(directory), deadline, max_pages, page_numbers):
            completed = subprocess.run(
                ["tesseract", str(image), "stdout", "-l", languages, "--psm", "6"],
                check=True,
                capture_output=True,
                timeout=remaining_time(deadline),
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
            )
            pages.append(ExtractedPage(page=page, text=normalize(completed.stdout.decode("utf-8"))))
    return pages
