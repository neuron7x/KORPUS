"""Server-authoritative projection consumed by browser clients.

The browser may render authorization and runtime capability decisions; it must not
reconstruct them from roles, local configuration, or DOM state. This projection keeps
identity, effective permissions, release identity and deploy-time capabilities in one
response so every UI surface observes the same server decision.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from korpus.application.policy import KNOWN_PERMISSIONS, PolicyEngine
from korpus.config import Settings
from korpus.domain.models import Identity
from korpus.release import RELEASE_TAG


class ClientCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    browser_auth_enabled: bool
    subscription_required: bool
    offline_pack_enabled: bool
    ingestion_mode: Literal["synchronous", "durable_async"]


class ClientBootstrap(BaseModel):
    model_config = ConfigDict(frozen=True)

    release: str
    api_version: str
    identity: Identity
    effective_permissions: tuple[str, ...]
    capabilities: ClientCapabilities


def effective_permissions(identity: Identity, policy: PolicyEngine) -> tuple[str, ...]:
    granted = policy.permissions(identity)
    allowed = KNOWN_PERMISSIONS if "*" in granted else granted.intersection(KNOWN_PERMISSIONS)
    return tuple(sorted(allowed))


def build_client_bootstrap(
    identity: Identity, settings: Settings, policy: PolicyEngine
) -> ClientBootstrap:
    return ClientBootstrap(
        release=RELEASE_TAG,
        api_version="v1",
        identity=identity,
        effective_permissions=effective_permissions(identity, policy),
        capabilities=ClientCapabilities(
            browser_auth_enabled=settings.browser_auth_enabled,
            subscription_required=settings.subscription_required,
            offline_pack_enabled=settings.offline_pack_enabled,
            ingestion_mode=settings.ingestion_mode,
        ),
    )
