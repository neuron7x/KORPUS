from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from korpus.infrastructure.identity_contracts import (
    parse_access_token_payload,
    validate_identity_config,
)

_METADATA_ROOT = "http://metadata.google.internal/computeMetadata/v1"
_ACCESS_TOKEN_URL = f"{_METADATA_ROOT}/instance/service-accounts/default/token"
_ID_TOKEN_URL = f"{_METADATA_ROOT}/instance/service-accounts/default/identity"
_METADATA_HEADERS = {"Metadata-Flavor": "Google"}


class MetadataIdentityError(RuntimeError):
    """The runtime could not obtain a workload credential from the GCP metadata server."""


@dataclass(frozen=True)
class _CachedToken:
    value: str
    refresh_at: float


class MetadataIdentityProvider:
    """Short-lived GCP workload credentials, cached without persistent key material.

    Cloud Run exposes the metadata server to the workload identity. The provider never
    accepts an operator-supplied metadata URL: making that URL configurable turns a
    credential primitive into an SSRF primitive. Tests inject an HTTP client instead.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 2.0,
        refresh_skew_seconds: int = 60,
        client: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        timeout_seconds, refresh_skew_seconds = validate_identity_config(
            timeout_seconds, refresh_skew_seconds
        )
        self._clock = clock
        self._refresh_skew_seconds = refresh_skew_seconds
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        )
        self._access_token: _CachedToken | None = None
        self._id_tokens: dict[str, _CachedToken] = {}
        self._lock = threading.RLock()

    def access_token(self) -> str:
        with self._lock:
            cached = self._access_token
            now = self._clock()
            if cached is not None and now < cached.refresh_at:
                return cached.value
            response = self._request("GET", _ACCESS_TOKEN_URL)
            try:
                token, expires_in, _token_type = parse_access_token_payload(response.json())
            except (TypeError, ValueError) as exc:
                raise MetadataIdentityError("metadata access-token response is invalid") from exc
            refresh_in = max(1, expires_in - self._refresh_skew_seconds)
            self._access_token = _CachedToken(token, now + refresh_in)
            return token

    def id_token(self, audience: str) -> str:
        if not audience.startswith("https://") or len(audience) > 2048:
            raise ValueError("ID-token audience must be an HTTPS URL")
        with self._lock:
            cached = self._id_tokens.get(audience)
            now = self._clock()
            if cached is not None and now < cached.refresh_at:
                return cached.value
            response = self._request(
                "GET",
                _ID_TOKEN_URL,
                params={"audience": audience, "format": "full"},
            )
            token = str(response.text).strip()
            if token.count(".") != 2 or len(token) < 32:
                raise MetadataIdentityError("metadata ID-token response is invalid")
            # Metadata identity tokens are currently issued with an approximately one-hour
            # lifetime. We deliberately cache for only five minutes; verification of `exp`
            # remains the receiving service's responsibility and short caching avoids a JWT
            # parser in this credential boundary.
            self._id_tokens[audience] = _CachedToken(token, now + 300)
            return token

    def authorization_header(self) -> str:
        return f"Bearer {self.access_token()}"

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(
                method,
                url,
                headers=_METADATA_HEADERS,
                **kwargs,
            )
            response.raise_for_status()
        except Exception as exc:
            raise MetadataIdentityError("GCP metadata identity is unavailable") from exc
        if str(response.headers.get("Metadata-Flavor", "Google")) != "Google":
            # Real metadata responses carry this header. Some HTTP test doubles omit it,
            # so the default preserves compatibility while an explicit hostile value fails.
            raise MetadataIdentityError("metadata server identity marker is invalid")
        return response
