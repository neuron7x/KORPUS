from __future__ import annotations

from korpus.application.offline_pack import OfflinePackService
from korpus.application.policy import PolicyEngine
from korpus.config import Settings
from korpus.infrastructure.offline_pack_signer import Ed25519OfflinePackSigner
from korpus.infrastructure.repository import SqlRepository


def build_offline_pack_service(
    settings: Settings, repository: SqlRepository, policy: PolicyEngine
) -> OfflinePackService | None:
    if not settings.offline_pack_enabled:
        return None
    path = settings.offline_pack_signing_key_file
    if path is None:
        raise ValueError("offline pack signing key file is required")
    signer = Ed25519OfflinePackSigner.load(path, settings.offline_pack_key_id)
    return OfflinePackService(
        repository,
        policy,
        signer,
        ttl_seconds=settings.offline_pack_ttl_seconds,
        max_spans=settings.offline_pack_max_spans,
    )
