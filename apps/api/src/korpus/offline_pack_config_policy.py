from __future__ import annotations

from typing import Any


def validate_offline_pack_settings(settings: Any) -> None:
    if not settings.offline_pack_enabled:
        return
    key_path = settings.offline_pack_signing_key_file
    if key_path is None or not key_path.is_file():
        raise ValueError("offline pack export requires an existing Ed25519 signing key file")
