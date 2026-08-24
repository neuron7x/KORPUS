from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from korpus.security.browser_oidc_urls import (
    authorization_url as build_authorization_url,
    canonical_https_endpoint,
)


class BrowserSessionError(ValueError):
    pass


class BrowserSessionCodec:
    """Authenticated, expiring browser state/session envelopes.

    The browser receives only opaque AES-GCM ciphertext. The access token remains
    HttpOnly and is never exposed to JavaScript.
    """

    def __init__(self, secret: str, *, clock: Any = time.time) -> None:
        if len(secret) < 32:
            raise ValueError("browser session secret must contain at least 32 characters")
        self._key = hashlib.sha256(secret.encode("utf-8")).digest()
        self._clock = clock

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        """Reject non-canonical encodings, not only undecodable ones.

        Unpadded base64 is malleable at the tail: when the byte length is not a
        multiple of three the final character carries bits no input byte uses, so
        several distinct tokens decode to identical plaintext and AES-GCM authenticates
        all of them. A session cookie is therefore not one string, and any check that
        compares, revokes or rate-limits by token text silently misses the variants.
        Re-encoding and comparing makes the mapping one-to-one.
        """
        padding = "=" * (-len(value) % 4)
        try:
            decoded = base64.urlsafe_b64decode(value + padding)
        except (ValueError, binascii.Error) as exc:
            raise BrowserSessionError("invalid browser session encoding") from exc
        if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
            raise BrowserSessionError("non-canonical browser session encoding")
        return decoded

    def seal(self, kind: str, payload: dict[str, Any], *, ttl_seconds: int) -> str:
        if not kind or ttl_seconds < 1:
            raise ValueError("invalid browser session envelope")
        now = int(self._clock())
        body = json.dumps(
            {"v": 1, "kind": kind, "iat": now, "exp": now + ttl_seconds, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, body, kind.encode("utf-8"))
        return self._encode(nonce + ciphertext)

    def open(self, token: str, *, expected_kind: str) -> dict[str, Any]:
        raw = self._decode(token)
        if len(raw) < 12 + 16:
            raise BrowserSessionError("browser session envelope is truncated")
        nonce, ciphertext = raw[:12], raw[12:]
        try:
            body = AESGCM(self._key).decrypt(
                nonce, ciphertext, expected_kind.encode("utf-8")
            )
            data = json.loads(body)
        # cryptographic parser boundary: all failures are indistinguishable
        except Exception as exc:
            raise BrowserSessionError("browser session authentication failed") from exc
        now = int(self._clock())
        if data.get("v") != 1 or data.get("kind") != expected_kind:
            raise BrowserSessionError("browser session type mismatch")
        if not isinstance(data.get("iat"), int) or not isinstance(data.get("exp"), int):
            raise BrowserSessionError("browser session timestamps are invalid")
        if data["iat"] > now + 30 or data["exp"] <= now:
            raise BrowserSessionError("browser session expired or not yet valid")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise BrowserSessionError("browser session payload is invalid")
        return payload


@dataclass(frozen=True)
class BrowserOIDCTokens:
    access_token: str
    id_token: str
    expires_in: int


class BrowserOIDCClient:
    def __init__(
        self,
        *,
        authorization_endpoint: str,
        token_endpoint: str,
        client_id: str,
        redirect_uri: str,
        scopes: list[str],
        client_secret: str | None = None,
        timeout_seconds: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        authorization_endpoint = canonical_https_endpoint(
            authorization_endpoint, name="OIDC authorization endpoint"
        )
        token_endpoint = canonical_https_endpoint(token_endpoint, name="OIDC token endpoint")
        if not client_id or not redirect_uri:
            raise ValueError("OIDC client id and redirect URI are required")
        self.authorization_endpoint = authorization_endpoint
        self.token_endpoint = token_endpoint
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.scopes = tuple(dict.fromkeys(["openid", *scopes]))
        self.client_secret = client_secret
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )

    @staticmethod
    def new_flow() -> dict[str, str]:
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        return {
            "state": secrets.token_urlsafe(32),
            "nonce": secrets.token_urlsafe(32),
            "code_verifier": verifier,
            "code_challenge": challenge,
            "csrf": secrets.token_urlsafe(32),
        }

    def authorization_url(self, flow: dict[str, str]) -> str:
        return build_authorization_url(
            self.authorization_endpoint,
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            scopes=self.scopes,
            flow=flow,
        )

    def exchange(self, code: str, code_verifier: str) -> BrowserOIDCTokens:
        if not code or not code_verifier:
            raise BrowserSessionError("OIDC authorization response is incomplete")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": code_verifier,
        }
        if self.client_secret is not None:
            data["client_secret"] = self.client_secret
        response = self.client.post(
            self.token_endpoint,
            data=data,
            headers={"Accept": "application/json"},
        )
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BrowserSessionError("OIDC token exchange failed") from exc
        access_token = payload.get("access_token")
        id_token = payload.get("id_token")
        expires_in = payload.get("expires_in", 300)
        if not isinstance(access_token, str) or not isinstance(id_token, str):
            raise BrowserSessionError("OIDC token response is incomplete")
        if not isinstance(expires_in, int) or not 60 <= expires_in <= 86400:
            raise BrowserSessionError("OIDC token lifetime is invalid")
        return BrowserOIDCTokens(access_token, id_token, expires_in)

    def close(self) -> None:
        self.client.close()
