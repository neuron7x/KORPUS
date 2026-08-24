"""Cloud-specific runtime factories, isolated from the portable runtime graph."""

from __future__ import annotations

from korpus.application.ports import ObjectStore
from korpus.config import Settings
from korpus.infrastructure.audit_anchor import (
    AuditAnchorStore,
    FileAuditAnchorStore,
    HttpAuditAnchorStore,
)
from korpus.infrastructure.gcs import GcsObjectStore
from korpus.infrastructure.gcs_audit_anchor import GcsAuditAnchorStore


def create_audit_anchor(settings: Settings, key: bytes) -> AuditAnchorStore:
    if settings.audit_anchor_mode == "http":
        return HttpAuditAnchorStore(
            settings.audit_anchor_url or "",
            key,
            token=settings.resolved_audit_anchor_token,
            timeout_seconds=settings.audit_anchor_timeout_seconds,
        )
    if settings.audit_anchor_mode == "gcs":
        return GcsAuditAnchorStore(
            settings.gcs_audit_bucket or "",
            key,
            prefix=settings.gcs_audit_prefix,
        )
    return FileAuditAnchorStore(settings.audit_anchor_path, key)


def create_gcs_store(settings: Settings, *, quarantine: bool) -> ObjectStore:
    bucket = settings.gcs_quarantine_bucket if quarantine else settings.gcs_bucket
    prefix = settings.gcs_quarantine_prefix if quarantine else settings.gcs_prefix
    retention = 0 if quarantine else settings.gcs_retention_seconds
    return GcsObjectStore(
        bucket=bucket or settings.gcs_bucket or "",
        prefix=prefix,
        retention_seconds=retention,
        max_object_bytes=settings.max_upload_bytes,
    )


def s3_bucket_name(settings: Settings) -> str:
    return settings.s3_bucket or ""
