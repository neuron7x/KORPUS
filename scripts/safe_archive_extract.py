"""Extraction primitive that refuses unsafe ZIPs before writing any member."""
from __future__ import annotations
import os
import zipfile
from pathlib import Path

from importlib import import_module
safety_failures = import_module(f"{__package__ + chr(46) if __package__ else chr(39)*0}zip_safety").safety_failures


def extract_safe_archive(archive: Path, destination: Path) -> Path:
    with zipfile.ZipFile(archive) as zf:
        failures = safety_failures(zf)
        if failures:
            raise RuntimeError("unsafe release ZIP: " + "; ".join(failures))
        zf.extractall(destination)
        for info in zf.infolist():
            if not info.is_dir():
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    os.chmod(destination / info.filename, mode)
    return next(destination.iterdir())
