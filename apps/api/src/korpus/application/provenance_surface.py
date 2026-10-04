"""Source-surface definition used by assurance provenance hashing."""

from __future__ import annotations

EVIDENCE_SOURCE_PATHS: tuple[str, ...] = (
    "apps/api",
    "apps/web",
    "packages",
    "contracts",
    "scripts",
    "config",
    "evals",
    "deploy",
    "infra",
    ".github/workflows",
    ".gitlab-ci.yml",
    "Makefile",
    "docker-compose.yml",
    ".dockerignore",
)
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        ".venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "var",
        "node_modules",
        "dist",
        ".terraform",
    }
)
EXCLUDED_SUFFIXES = (".pyc", ".pyo")
