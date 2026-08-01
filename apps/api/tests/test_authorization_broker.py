from __future__ import annotations

import base64
import json

import jwt
from fastapi.testclient import TestClient

from korpus.authorization_broker import BrokerRuntime, create_broker_app
from korpus.domain.models import AccessTier
from korpus.security.database_capability import DatabaseCapabilityIssuer
from korpus.security.entitlements import EntitlementGrant, EntitlementProfile


class Verifier:
    def verify(self, token: str) -> dict[str, object]:
        if token != "valid-upstream-token":
            raise jwt.InvalidTokenError("invalid")
        return {
            "iss": "https://id.example",
            "aud": "korpus-api",
            "sub": "curator-1",
            "groups": ["curators"],
        }


def decode(token: str) -> dict[str, object]:
    encoded = token.split(".", 1)[0]
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))


def runtime() -> BrokerRuntime:
    profile = EntitlementProfile(
        profile_id="broker-test",
        issuer="https://id.example",
        audience="korpus-api",
        groups={
            "curators": EntitlementGrant(
                roles=frozenset({"user", "curator"}),
                clearance=AccessTier.RESTRICTED,
                corpora=frozenset({"restricted-demo"}),
                compartments=frozenset({"omega"}),
            )
        },
    )
    return BrokerRuntime(
        verifier=Verifier(),
        entitlements=profile,
        issuer=DatabaseCapabilityIssuer("broker-test-key", b"k" * 32),
    )


def test_broker_derives_scope_from_verified_entitlements_not_request_body() -> None:
    with TestClient(create_broker_app(runtime())) as client:
        response = client.post(
            "/v1/database-capabilities",
            headers={"Authorization": "Bearer valid-upstream-token"},
            json={
                "roles": ["admin"],
                "corpora": ["everything"],
                "operations": ["delete"],
            },
        )
    assert response.status_code == 200
    payload = decode(response.json()["capability"])
    assert payload["sub"] == "curator-1"
    assert payload["roles"] == ["curator", "user"]
    assert payload["corpora"] == ["public", "restricted-demo"]
    assert payload["compartments"] == ["omega"]
    assert payload["operations"] == ["read", "write"]


def test_broker_rejects_missing_and_invalid_upstream_credentials() -> None:
    with TestClient(create_broker_app(runtime())) as client:
        assert client.post("/v1/database-capabilities").status_code == 401
        assert client.post(
            "/v1/database-capabilities",
            headers={"Authorization": "Bearer attacker"},
        ).status_code == 403


def test_broker_rejects_unsafe_capability_lifetime() -> None:
    base = runtime()
    try:
        BrokerRuntime(base.verifier, base.entitlements, base.issuer, lifetime_seconds=61)
    except ValueError as exc:
        assert "between 5 and 60" in str(exc)
    else:
        raise AssertionError("unsafe lifetime was accepted")


def test_broker_limits_worker_to_read_and_write() -> None:
    profile = EntitlementProfile(
        profile_id="worker-test",
        issuer="https://id.example",
        audience="korpus-api",
        groups={
            "curators": EntitlementGrant(
                roles=frozenset({"worker"}),
                clearance=AccessTier.AUTHENTICATED,
                corpora=frozenset({"public"}),
            )
        },
    )
    broker = BrokerRuntime(
        verifier=Verifier(),
        entitlements=profile,
        issuer=DatabaseCapabilityIssuer("broker-test-key", b"k" * 32),
    )

    payload = decode(broker.issue("valid-upstream-token"))

    assert payload["operations"] == ["read", "write"]
