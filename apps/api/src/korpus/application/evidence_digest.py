"""Canonical digest of source bytes that can change assurance evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

EVIDENCE_SOURCE_PATHS: tuple[str, ...] = (
    "Makefile",
    ".github/workflows/assurance.yml",
    "apps/api/src",
    "apps/api/tests",
    "apps/api/migrations",
    "apps/api/alembic.ini",
    "apps/api/pyproject.toml",
    "apps/api/requirements.dev.lock",
    "apps/api/requirements.runtime.lock",
    "packages",
    "scripts",
    "config",
    "evals",
)

_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        ".venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "var",
        "node_modules",
    }
)
_EXCLUDED_SUFFIXES = (".pyc", ".pyo")
_DIGEST_DOMAIN = b"korpus-source-digest-v1\0"


def evidence_source_path_included(relative: str | Path) -> bool:
    path = Path(relative)
    excluded_directory = any(part in _EXCLUDED_DIRECTORY_NAMES for part in path.parts)
    return not excluded_directory and path.suffix not in _EXCLUDED_SUFFIXES


def digest_source_records(records: Iterable[tuple[str, bytes]]) -> str:
    """Hash path/content records with one deterministic framing algorithm."""

    normalized: dict[str, bytes] = {}
    for relative, content in records:
        canonical = Path(relative).as_posix()
        if canonical in normalized:
            raise ValueError(f"duplicate source-digest path: {canonical}")
        normalized[canonical] = content

    hasher = hashlib.sha256()
    hasher.update(_DIGEST_DOMAIN)
    for relative in sorted(normalized):
        encoded = relative.encode("utf-8")
        content = normalized[relative]
        hasher.update(len(encoded).to_bytes(4, "big"))
        hasher.update(encoded)
        hasher.update(len(content).to_bytes(8, "big"))
        hasher.update(content)
    return hasher.hexdigest()


def _digest_candidates(root: Path, sources: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for relative in sources:
        target = root / relative
        if target.is_file():
            files.append(target)
            continue
        if not target.is_dir():
            continue
        files.extend(
            path
            for path in target.rglob("*")
            if path.is_file() and evidence_source_path_included(path.relative_to(root))
        )
    return sorted(set(files), key=lambda path: path.relative_to(root).as_posix())


def compute_source_digest(root: Path, sources: Iterable[str] = EVIDENCE_SOURCE_PATHS) -> str:
    """Digest the live evidence-bearing working-tree surface."""

    return digest_source_records(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in _digest_candidates(root, sources)
    )
