from korpus.application.client_bootstrap import build_client_bootstrap
from korpus.application.policy import KNOWN_PERMISSIONS, PolicyEngine
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity

from apps.api.tests.conftest import set_identity


def _identity(*roles: str) -> Identity:
    return Identity(
        subject="bootstrap-user",
        roles=frozenset(roles),
        clearance=AccessTier.AUTHENTICATED,
        corpora=frozenset({"public"}),
    )


def test_bootstrap_expands_admin_wildcard_to_closed_permission_vocabulary():
    projected = build_client_bootstrap(
        _identity("admin"), Settings(environment="test", auth_mode="disabled"), PolicyEngine()
    )
    assert projected.effective_permissions == tuple(sorted(KNOWN_PERMISSIONS))
    assert "*" not in projected.effective_permissions


def test_bootstrap_projects_runtime_capabilities_without_client_reconstruction(tmp_path):
    key = tmp_path / "offline.key"
    key.write_bytes(b"k" * 32)
    projected = build_client_bootstrap(
        _identity("user"),
        Settings(
            environment="test",
            auth_mode="disabled",
            browser_auth_enabled=False,
            subscription_required=True,
            offline_pack_enabled=True,
            offline_pack_signing_key_file=key,
            ingestion_mode="durable_async",
        ),
        PolicyEngine(),
    )
    assert projected.release == "v0.9.7"
    assert projected.api_version == "v1"
    assert projected.effective_permissions == ("answer:read", "document:list")
    assert projected.capabilities.model_dump() == {
        "browser_auth_enabled": False,
        "subscription_required": True,
        "offline_pack_enabled": True,
        "ingestion_mode": "durable_async",
    }


def test_bootstrap_route_returns_same_identity_and_effective_permissions(client):
    set_identity(client, _identity("auditor"))
    response = client.get("/v1/client/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["identity"]["subject"] == "bootstrap-user"
    assert payload["effective_permissions"] == ["audit:read", "audit:verify", "document:list"]
    assert payload["release"] == "v0.9.7"
