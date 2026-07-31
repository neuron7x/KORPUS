from __future__ import annotations

from korpus.application.policy import PolicyEngine
from korpus.application.ports import ObjectStore
from korpus.config import Settings
from korpus.infrastructure.audit_anchor import FileAuditAnchorStore, HttpAuditAnchorStore
from korpus.infrastructure.object_store import LocalObjectStore, S3ObjectStore
from korpus.infrastructure.repository import SqlRepository


def create_repository(settings: Settings, policy: PolicyEngine | None = None) -> SqlRepository:
    audit_key = settings.resolved_audit_hmac_key.encode("utf-8")
    anchor = (
        HttpAuditAnchorStore(
            settings.audit_anchor_url or "",
            audit_key,
            token=settings.resolved_audit_anchor_token,
            timeout_seconds=settings.audit_anchor_timeout_seconds,
        )
        if settings.audit_anchor_mode == "http"
        else FileAuditAnchorStore(settings.audit_anchor_path, audit_key)
    )
    return SqlRepository(
        settings.database_url,
        settings.resolved_audit_hmac_key,
        policy,
        settings.audit_anchor_path,
        anchor,
    )


def create_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store_mode == "s3":
        return S3ObjectStore(
            bucket=settings.s3_bucket or "",
            prefix=settings.s3_prefix,
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            governance_retention_days=settings.s3_governance_retention_days,
        )
    return LocalObjectStore(settings.object_root)
