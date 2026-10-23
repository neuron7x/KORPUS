"""Fail-closed ZIP admission followed by failure-atomic publication."""

from __future__ import annotations

import zipfile
from importlib import import_module
from pathlib import Path

_prefix = f"{__package__}." if __package__ else ""
safety_failures = import_module(_prefix + "zip_safety").safety_failures
publish_safe_zip = import_module(_prefix + "archive_atomic_publish").publish_safe_zip


def extract_safe_archive(archive: Path, destination: Path) -> Path:
    with zipfile.ZipFile(archive) as zf:
        failures = safety_failures(zf)
        if failures:
            raise RuntimeError("unsafe release ZIP: " + "; ".join(failures))
        return publish_safe_zip(zf, destination)
