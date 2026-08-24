"""Trusted-key rotation and revocation for signed offline knowledge packs."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from korpus.application.military_assurance import (
    OfflinePackState,
    OfflinePackVerification,
    verify_offline_pack,
)


class TrustedOfflineKey(BaseModel):
    model_config = ConfigDict(frozen=True)
    key_id: str = Field(pattern=r"^[a-zA-Z0-9._:-]{1,128}$")
    public_key_b64: str = Field(min_length=16, max_length=512)
    valid_from: datetime
    valid_until: datetime | None = None
    revoked_at: datetime | None = None

    def trusted_at(self, observed: datetime) -> bool:
        point = observed.astimezone(UTC)
        return (
            self.valid_from.astimezone(UTC) <= point
            and (self.valid_until is None or point <= self.valid_until.astimezone(UTC))
            and (self.revoked_at is None or point < self.revoked_at.astimezone(UTC))
        )


class OfflineTrustStore(BaseModel):
    model_config = ConfigDict(frozen=True)
    keys: tuple[TrustedOfflineKey, ...] = Field(min_length=1, max_length=128)

    def by_id(self) -> dict[str, TrustedOfflineKey]:
        out: dict[str, TrustedOfflineKey] = {}
        for item in self.keys:
            if item.key_id in out:
                raise ValueError(f"duplicate offline trust key: {item.key_id}")
            out[item.key_id] = item
        return out


def verify_with_trust_store(
    pack: dict[str, object],
    trust_store: OfflineTrustStore,
    *,
    now: datetime | None = None,
) -> OfflinePackVerification:
    """Resolve pack key id through a time-bounded trust store, then verify signature."""
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    key_id = pack.get("key_id")
    if not isinstance(key_id, str):
        return OfflinePackVerification(state=OfflinePackState.SIGNATURE_INVALID, usable=False)
    key = trust_store.by_id().get(key_id)
    if key is None or not key.trusted_at(observed):
        return OfflinePackVerification(state=OfflinePackState.SIGNATURE_INVALID, usable=False)
    return verify_offline_pack(pack, trusted_public_key_b64=key.public_key_b64, now=observed)
