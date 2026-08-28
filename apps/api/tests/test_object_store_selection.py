"""Which store a deployment gets, and the two checks that decide a GCS bucket is usable.

`create_object_store` and `create_quarantine_store` translate one setting into three very
different backends. Measured on 2026-08-28 only the local arm had ever been taken, so a
change to the S3 or GCS branch — a swapped bucket, a dropped prefix, quarantine pointed
at the content bucket — would not have turned the suite red.

The quarantine split is the one that matters most. Unscanned uploads and admitted content
live in the same bucket under different prefixes; if the quarantine store returned the
content prefix, a file would be readable before it had been scanned.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from korpus.config import Settings
from korpus.infrastructure.gcs import GcsObjectStore
from korpus.infrastructure.object_store import LocalObjectStore, S3ObjectStore
from korpus.infrastructure.runtime import create_object_store, create_quarantine_store


def _settings(tmp_path: Path, **changes: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": f"sqlite:///{tmp_path / 'store.db'}",
        "object_root": tmp_path / "objects",
        "quarantine_object_root": tmp_path / "quarantine",
        "audit_anchor_path": tmp_path / "anchor.json",
        "audit_hmac_key": "store-selection-audit-key-000000000000",
        "auth_mode": "dev",
        "dev_mode_acknowledgement": "I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


def test_the_default_deployment_gets_a_local_store(tmp_path: Path) -> None:
    """The dual: without it the two assertions below could pass on a broken selector."""
    settings = _settings(tmp_path)
    assert isinstance(create_object_store(settings), LocalObjectStore)
    assert isinstance(create_quarantine_store(settings), LocalObjectStore)


def test_an_unknown_store_mode_is_refused_by_configuration(tmp_path: Path) -> None:
    """Falling through to local on an unrecognised mode is the dangerous default.

    An operator who typed `gcs2` would get a local store on a machine with no persistent
    disk, and the first restart would take the corpus with it.
    """
    with pytest.raises(ValueError, match="object_store_mode must be"):
        _settings(tmp_path, object_store_mode="gcs2")


def test_s3_mode_selects_the_s3_store_and_keeps_quarantine_on_its_own_prefix(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        object_store_mode="s3",
        s3_bucket="korpus-objects",
        s3_prefix="content",
        s3_quarantine_prefix="quarantine",
        s3_region="eu-central-1",
    )
    content = create_object_store(settings)
    quarantine = create_quarantine_store(settings)
    assert isinstance(content, S3ObjectStore)
    assert isinstance(quarantine, S3ObjectStore)
    assert content.prefix != quarantine.prefix, (
        "quarantine sharing the content prefix makes unscanned uploads readable"
    )


def test_gcs_mode_selects_the_gcs_store_and_keeps_quarantine_on_its_own_prefix(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        object_store_mode="gcs",
        gcs_bucket="korpus-objects",
        gcs_prefix="content",
        gcs_quarantine_prefix="quarantine",
    )
    content = create_object_store(settings)
    quarantine = create_quarantine_store(settings)
    assert isinstance(content, GcsObjectStore)
    assert isinstance(quarantine, GcsObjectStore)
    assert content.prefix != quarantine.prefix
