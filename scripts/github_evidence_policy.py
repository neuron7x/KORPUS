"""Fixed API authority, exact comparison route and shared fail-closed refusals."""

from __future__ import annotations

import re
from urllib.parse import unquote

from korpus.application.github_release_context import CANONICAL_GITHUB_REPOSITORY

API_HOST = "api.github.com"
API_PREFIX = f"/repos/{CANONICAL_GITHUB_REPOSITORY}"


class GitHubEvidenceError(ValueError):
    """An authoritative subject or its immutable bytes could not be established."""


def insist(condition: bool, message: str) -> None:
    if not condition:
        raise GitHubEvidenceError(message)


def valid_api_path(relative: str) -> bool:
    decoded = unquote(relative)
    if decoded.startswith("/compare/"):
        return (
            re.fullmatch(r"/compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}\?per_page=1&page=2", relative)
            is not None
        )
    return relative.startswith("/") and ".." not in decoded and "#" not in relative
