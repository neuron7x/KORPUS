"""Cross-field policy for durable runtime integrations."""
from __future__ import annotations

from typing import Any


def validate_storage_integrations(settings: Any, *, controlled: bool) -> None:
    if settings.audit_anchor_mode == "http" and not settings.audit_anchor_url:
        raise ValueError("audit_anchor_url is required for HTTP audit anchoring")
    if settings.audit_anchor_mode == "gcs" and not settings.gcs_audit_bucket:
        raise ValueError("gcs_audit_bucket is required for GCS audit anchoring")
    if settings.object_store_mode == "s3" and not settings.s3_bucket:
        raise ValueError("s3_bucket is required for S3 object storage")
    if settings.object_store_mode == "gcs" and not settings.gcs_bucket:
        raise ValueError("gcs_bucket is required for GCS object storage")
    if controlled and settings.object_store_mode == "local":
        raise ValueError("controlled environments require durable remote object storage")
