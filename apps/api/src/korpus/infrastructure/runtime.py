from __future__ import annotations

from korpus.application.policy import PolicyEngine
from korpus.application.ports import ObjectStore
from korpus.config import Settings
from korpus.infrastructure.object_store import LocalObjectStore, S3ObjectStore
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.rls_repository import RlsBoundSqlRepository
from korpus.infrastructure.runtime_cloud import (
    create_audit_anchor,
    create_gcs_store,
    s3_bucket_name,
)


def create_repository(settings: Settings, policy: PolicyEngine | None = None) -> SqlRepository:
    audit_key = settings.resolved_audit_hmac_key.encode("utf-8")
    anchor = create_audit_anchor(settings, audit_key)
    # На PostgreSQL репозиторій ЗАВЖДИ той, що не дає підробити claim: політики
    # читають довірену таблицю, а не `current_setting`, який пише сам застосунок.
    # Обирати тут між двома реалізаціями за прапорцем означало б лишити ввімкнену
    # дірку одним рядком конфігурації.
    factory = (
        RlsBoundSqlRepository if settings.database_url.startswith("postgresql") else SqlRepository
    )
    extra: dict[str, object] = {}
    if settings.database_url.startswith("postgresql"):
        extra["authz_database_url"] = settings.authz_database_url
        extra["review_database_url"] = settings.review_database_url
    return factory(
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
        # Іменована, бо вставка поруч із ключем зсунула б позиційні аргументи — це вже
        # ставалось і віддало `FileAuditAnchorStore` самому собі як шлях.
        audit_keyring=settings.resolved_audit_keyring(),
        **extra,  # type: ignore[arg-type]
    )


def create_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store_mode == "gcs":
        return create_gcs_store(settings, quarantine=False)
    if settings.object_store_mode == "s3":
        return S3ObjectStore(
            bucket=s3_bucket_name(settings),
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
    if settings.object_store_mode == "gcs":
        return create_gcs_store(settings, quarantine=True)
    if settings.object_store_mode == "s3":
        return S3ObjectStore(
            bucket=s3_bucket_name(settings),
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
