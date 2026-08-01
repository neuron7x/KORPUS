from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
import httpx

from korpus.domain.models import AccessTier, Identity
from korpus.security.database_capability import (
    DatabaseCapabilityIssuer,
    HttpDatabaseCapabilityProvider,
    LocalDatabaseCapabilityProvider,
)


def decode_payload(token: str) -> dict[str, object]:
    encoded = token.split(".", 1)[0]
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))


def test_capability_is_canonical_and_binds_complete_scope() -> None:
    issuer = DatabaseCapabilityIssuer("test-key", b"k" * 32)
    identity = Identity(
        subject="authorized-user",
        roles=frozenset({"user", "curator"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"restricted-demo", "public"}),
        compartments=frozenset({"omega"}),
    )
    start = datetime(2026, 8, 2, tzinfo=UTC)
    first = issuer.issue(
        identity,
        jti="one-use-id",
        not_before=start,
        expires_at=start + timedelta(seconds=60),
        operations=frozenset({"read", "write"}),
    )
    second = issuer.issue(
        identity,
        jti="one-use-id",
        not_before=start,
        expires_at=start + timedelta(seconds=60),
        operations=frozenset({"write", "read"}),
    )
    assert first == second
    payload = decode_payload(first)
    assert payload == {
        "aud": "korpus-db",
        "classifications": ["public", "internal", "restricted"],
        "clearance": 3,
        "compartments": ["omega"],
        "corpora": ["public", "restricted-demo"],
        "exp": 1785628860,
        "jti": "one-use-id",
        "key_id": "test-key",
        "nbf": 1785628800,
        "operations": ["read", "write"],
        "roles": ["curator", "user"],
        "sub": "authorized-user",
        "v": 1,
    }


@pytest.mark.parametrize(
    ("key_id", "key", "match"),
    [("", b"k" * 32, "key_id"), ("key", b"short", "32 bytes")],
)
def test_issuer_rejects_invalid_key_material(key_id: str, key: bytes, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        DatabaseCapabilityIssuer(key_id, key)


def test_issuer_rejects_invalid_lifetime_and_operations() -> None:
    issuer = DatabaseCapabilityIssuer("key", b"k" * 32)
    identity = Identity(subject="u")
    now = datetime(2026, 8, 2, tzinfo=UTC)
    with pytest.raises(ValueError, match="expiry"):
        issuer.issue(identity, jti="j", not_before=now, expires_at=now)
    with pytest.raises(ValueError, match="unsupported"):
        issuer.issue(
            identity,
            jti="j",
            not_before=now,
            expires_at=now + timedelta(seconds=1),
            operations=frozenset({"admin-everything"}),
        )


def test_http_provider_forwards_credential_without_app_selected_claims() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers.get("Authorization")
        observed["body"] = request.content
        return httpx.Response(200, json={"capability": "x" * 66})

    provider = HttpDatabaseCapabilityProvider(
        "https://authz.example/v1/database-capabilities"
    )
    provider.client.close()
    provider.client = httpx.Client(transport=httpx.MockTransport(handler))
    identity = Identity(subject="u", authorization_credential="original-oidc-token")
    assert provider.issue(identity) == "x" * 66
    assert observed == {
        "authorization": "Bearer original-oidc-token",
        "body": b"",
    }
    provider.close()


def test_http_provider_fails_closed_without_credential_or_valid_response() -> None:
    provider = HttpDatabaseCapabilityProvider(
        "https://authz.example/v1/database-capabilities"
    )
    with pytest.raises(PermissionError, match="credential"):
        provider.issue(Identity(subject="u"))
    provider.client.close()
    provider.client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    with pytest.raises(PermissionError, match="invalid response"):
        provider.issue(Identity(subject="u", authorization_credential="token"))
    provider.close()


def test_http_provider_reads_rotatable_workload_credential(tmp_path) -> None:
    credential = tmp_path / "workload-token"
    credential.write_text("workload-v1", encoding="utf-8")
    observed: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"capability": "x" * 66})

    provider = HttpDatabaseCapabilityProvider(
        "https://authz.example/v1/database-capabilities",
        workload_credential_file=credential,
    )
    provider.client.close()
    provider.client = httpx.Client(transport=httpx.MockTransport(handler))
    identity = Identity(subject="worker")
    provider.issue(identity)
    credential.write_text("workload-v2", encoding="utf-8")
    provider.issue(identity)
    assert observed == ["Bearer workload-v1", "Bearer workload-v2"]
    provider.close()


def test_local_provider_is_short_lived_unique_and_role_bounded(tmp_path) -> None:
    key = tmp_path / "local-key"
    key.write_bytes(b"k" * 32)
    provider = LocalDatabaseCapabilityProvider("local", key)
    curator = Identity(subject="c", roles=frozenset({"curator"}))
    first = decode_payload(provider.issue(curator))
    second = decode_payload(provider.issue(curator))
    assert first["jti"] != second["jti"]
    assert first["operations"] == ["read", "write"]
    assert int(first["exp"]) - int(first["nbf"]) <= 31
    assert "delete" not in first["operations"]
