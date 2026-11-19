"""Bounded GitHub GET transport. No candidate URL or saved receipt grants authority."""

from __future__ import annotations

import http.client
import os
import ssl
from typing import Any
from urllib.parse import urlsplit

from korpus.application.github_release_context import CANONICAL_GITHUB_REPOSITORY
from korpus.application.strict_json import strict_json_object

API_HOST = "api.github.com"
API_PREFIX = f"/repos/{CANONICAL_GITHUB_REPOSITORY}"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_REQUESTS = 32
TIMEOUT_SECONDS = 30


class GitHubEvidenceError(ValueError):
    """An authoritative subject or its immutable bytes could not be established."""


def insist(condition: bool, message: str) -> None:
    if not condition:
        raise GitHubEvidenceError(message)


def strict_object(payload: bytes, label: str) -> dict[str, Any]:
    insist(len(payload) <= MAX_JSON_BYTES, f"{label}: JSON byte budget exceeded")
    return dict(strict_json_object(payload, label))


def object_record(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GitHubEvidenceError(label)
    return value


def object_records(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise GitHubEvidenceError(label)
    return value


def _download_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    insist(
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and parsed.port in {None, 443}
        and host.endswith((".blob.core.windows.net", ".actions.githubusercontent.com")),
        "GitHub download redirect is outside the HTTPS storage allowlist",
    )
    return host, parsed.path + ("?" + parsed.query if parsed.query else "")


class GitHubTransport:
    def __init__(self) -> None:
        self._token = os.environ.get("GITHUB_TOKEN", "")
        self._requests = 0
        self._tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._tls.load_verify_locations(cafile="/etc/ssl/certs/ca-certificates.crt")

    def _get(self, host: str, path: str, limit: int) -> tuple[int, str | None, bytes]:
        self._requests += 1
        insist(self._requests <= MAX_REQUESTS, "GitHub request budget exceeded")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "KORPUS-hosted-evidence/1",
        }
        # Public PR metadata needs no token or pull-request permission; Actions downloads do.
        if host == API_HOST and self._token and not path.startswith(API_PREFIX + "/pulls/"):
            headers["Authorization"] = "Bearer " + self._token
        connection = http.client.HTTPSConnection(host, timeout=TIMEOUT_SECONDS, context=self._tls)
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            payload = response.read(limit + 1)
            insist(len(payload) <= limit, "GitHub response byte budget exceeded")
            return response.status, response.getheader("Location"), payload
        except GitHubEvidenceError:
            raise
        except (OSError, ValueError, http.client.HTTPException) as error:
            raise GitHubEvidenceError("GitHub HTTPS request failed") from error
        finally:
            connection.close()

    def _api(self, relative: str, limit: int) -> tuple[int, str | None, bytes]:
        insist(relative.startswith("/") and ".." not in relative, "invalid GitHub API path")
        return self._get(API_HOST, API_PREFIX + relative, limit)

    def json(self, relative: str) -> dict[str, Any]:
        status, _location, payload = self._api(relative, MAX_METADATA_BYTES)
        insist(status == 200, f"GitHub metadata request refused: HTTP {status}")
        return strict_object(payload, "GitHub API response")

    def collection(self, relative: str, key: str) -> list[dict[str, Any]]:
        separator = "&" if "?" in relative else "?"
        data = self.json(relative + separator + "per_page=100")
        records = object_records(data.get(key), f"GitHub {key} collection is malformed")
        insist(
            len(records) <= 100
            and type(data.get("total_count")) is int
            and data["total_count"] == len(records),
            f"GitHub {key} collection is incomplete or exceeds its item budget",
        )
        return records

    def download(self, relative: str, limit: int) -> bytes:
        status, location, payload = self._api(relative, limit)
        for _redirect in range(3):
            if status == 200:
                return payload
            if status != 302 or not isinstance(location, str):
                raise GitHubEvidenceError("GitHub download failed")
            host, path = _download_url(location)
            status, location, payload = self._get(host, path, limit)
        raise GitHubEvidenceError("GitHub download redirect budget exceeded")
