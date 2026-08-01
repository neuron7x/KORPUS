from __future__ import annotations

from korpus.application.policy import PolicyEngine
from korpus.application.ports import ObjectStore
from korpus.config import Settings
from korpus.infrastructure.audit_anchor import FileAuditAnchorStore, HttpAuditAnchorStore
from korpus.infrastructure.object_store import LocalObjectStore, S3ObjectStore
from korpus.infrastructure.repository import SqlRepository
from korpus.security.database_capability import (
    HttpDatabaseCapabilityProvider,
    LocalDatabaseCapabilityProvider,
)


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
    capability_provider = (
        HttpDatabaseCapabilityProvider(
            settings.database_capability_broker_url,
            timeout_seconds=settings.database_capability_broker_timeout_seconds,
            ca_file=settings.database_capability_broker_ca_file,
            workload_credential_file=settings.database_capability_workload_credential_file,
        )
        if settings.database_capability_broker_url is not None
        else (
            LocalDatabaseCapabilityProvider(
                settings.database_capability_local_key_id,
                settings.database_capability_local_key_file,
            )
            if settings.database_capability_local_key_file is not None
            and settings.environment in {"local", "test", "development"}
            else None
        )
    )
    return SqlRepository(
        settings.database_url,
        settings.resolved_audit_hmac_key,
        policy,
        settings.audit_anchor_path,
        anchor,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout_seconds=settings.database_pool_timeout_seconds,
        pool_recycle_seconds=settings.database_pool_recycle_seconds,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
        statement_timeout_ms=settings.database_statement_timeout_ms,
        lock_timeout_ms=settings.database_lock_timeout_ms,
        database_capability_provider=capability_provider,
    )


def create_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store_mode == "s3":
        return S3ObjectStore(
            bucket=settings.s3_bucket or "",
            prefix=settings.s3_prefix,
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            governance_retention_days=settings.s3_governance_retention_days,
            force_path_style=settings.s3_force_path_style,
            connect_timeout_seconds=settings.s3_connect_timeout_seconds,
            read_timeout_seconds=settings.s3_read_timeout_seconds,
            max_attempts=settings.s3_max_attempts,
            max_object_bytes=settings.max_upload_bytes,
        )
    return LocalObjectStore(settings.object_root, max_object_bytes=settings.max_upload_bytes)


def create_quarantine_store(settings: Settings) -> ObjectStore:
    if settings.object_store_mode == "s3":
        return S3ObjectStore(
            bucket=settings.s3_bucket or "",
            prefix=settings.s3_quarantine_prefix,
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            governance_retention_days=settings.s3_governance_retention_days,
            force_path_style=settings.s3_force_path_style,
            connect_timeout_seconds=settings.s3_connect_timeout_seconds,
            read_timeout_seconds=settings.s3_read_timeout_seconds,
            max_attempts=settings.s3_max_attempts,
            max_object_bytes=settings.max_upload_bytes,
        )
    return LocalObjectStore(
        settings.quarantine_object_root, max_object_bytes=settings.max_upload_bytes
    )
