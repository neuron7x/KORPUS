from __future__ import annotations

import base64
import hashlib
from datetime import date
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from korpus.domain.models import AuthorityClass, VersionCreate
from korpus.security.source_authenticity import SourceTrustKey, SourceTrustProfile

PRIVATE = Ed25519PrivateKey.from_private_bytes(b"\x19" * 32)
PUBLIC_B64 = base64.b64encode(
    PRIVATE.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
).decode("ascii")


def key(**updates: object) -> SourceTrustKey:
    values: dict[str, object] = {
        "key_id": "official-key",
        "issuer": "Official Issuer",
        "public_key_b64": PUBLIC_B64,
        "authorities": frozenset({AuthorityClass.OFFICIAL_UA}),
    }
    values.update(updates)
    return SourceTrustKey(**values)


def profile(value: SourceTrustKey | None = None) -> SourceTrustProfile:
    selected = value or key()
    return SourceTrustProfile(profile_id="official-profile", keys={selected.key_id: selected})


def signed_version(
    trust: SourceTrustProfile,
    version: VersionCreate | None = None,
    *,
    source_hash: str = "a" * 64,
) -> VersionCreate:
    unsigned = version or VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA)
    signature = PRIVATE.sign(
        trust.signed_payload(
            issuer="Official Issuer", version=unsigned, source_hash=source_hash
        )
    )
    return unsigned.model_copy(
        update={
            "source_key_id": "official-key",
            "source_signature_b64": base64.b64encode(signature).decode("ascii"),
        }
    )


def test_key_and_profile_structure_fail_closed(tmp_path):
    with pytest.raises(ValidationError, match="validity interval"):
        key(valid_from=date(2026, 2, 1), valid_until=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        key(public_key_b64="!" * 44)
    with pytest.raises(ValidationError, match="32 bytes"):
        key(public_key_b64=base64.b64encode(b"x" * 31).decode())
    with pytest.raises(ValidationError, match="at least one key"):
        SourceTrustProfile(profile_id="empty-profile", keys={})
    with pytest.raises(ValidationError, match="does not match"):
        SourceTrustProfile(profile_id="bad-map", keys={"different-key": key()})

    trust = profile()
    path = tmp_path / "trust.json"
    raw = trust.model_dump_json().encode()
    path.write_bytes(raw)
    assert SourceTrustProfile.load(path) == trust
    assert SourceTrustProfile.load(path, hashlib.sha256(raw).hexdigest()) == trust
    with pytest.raises(ValueError, match="digest mismatch"):
        SourceTrustProfile.load(path, "0" * 64)


def test_signed_payload_canonically_binds_optional_metadata():
    version = VersionCreate(
        revision="2",
        authority=AuthorityClass.OFFICIAL_UA,
        publication_date=date(2026, 1, 2),
        effective_from=date(2026, 1, 3),
        effective_until=date(2026, 12, 31),
        publication_identifier="ORDER-2",
        source_uri="https://example.test/order/2",
        supersedes_version_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    payload = SourceTrustProfile.signed_payload(
        issuer="Official Issuer", version=version, source_hash="b" * 64
    )
    assert payload == SourceTrustProfile.signed_payload(
        issuer="Official Issuer", version=version, source_hash="b" * 64
    )
    assert b'"effective_from":"2026-01-03"' in payload
    assert b'"supersedes_version_id":"00000000-0000-0000-0000-000000000001"' in payload


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.model_copy(update={"source_key_id": None}), "required"),
        (lambda value: value.model_copy(update={"source_signature_b64": None}), "required"),
        (lambda value: value.model_copy(update={"source_key_id": "unknown"}), "unknown"),
        (lambda value: value.model_copy(update={"source_signature_b64": "!bad"}), "verification"),
        (lambda value: value.model_copy(update={"revision": "tampered"}), "verification"),
    ],
)
def test_signature_envelope_rejects_missing_unknown_malformed_and_tampered(mutate, message):
    trust = profile()
    version = signed_version(trust)
    with pytest.raises(ValueError, match=message):
        trust.verify(issuer="Official Issuer", version=mutate(version), source_hash="a" * 64)


def test_key_authority_issuer_revocation_and_time_boundaries_fail_closed():
    unsigned = VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA)
    signed = signed_version(profile(), unsigned)
    with pytest.raises(ValueError, match="revoked"):
        profile(key(revoked=True)).verify(
            issuer="Official Issuer", version=signed, source_hash="a" * 64
        )
    with pytest.raises(ValueError, match="issuer mismatch"):
        profile().verify(issuer="Other Issuer", version=signed, source_hash="a" * 64)
    with pytest.raises(ValueError, match="authority class"):
        profile(key(authorities=frozenset({AuthorityClass.HISTORICAL}))).verify(
            issuer="Official Issuer", version=signed, source_hash="a" * 64
        )
    bounded = profile(key(valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31)))
    with pytest.raises(ValueError, match="dated source signature"):
        bounded.verify(issuer="Official Issuer", version=signed, source_hash="a" * 64)

    for reference, message in (
        (date(2025, 12, 31), "predates"),
        (date(2027, 1, 1), "postdates"),
    ):
        dated = VersionCreate(
            revision="1", authority=AuthorityClass.OFFICIAL_UA, publication_date=reference
        )
        with pytest.raises(ValueError, match=message):
            bounded.verify(
                issuer="Official Issuer",
                version=signed_version(bounded, dated),
                source_hash="a" * 64,
            )


def test_valid_signature_is_clock_independent_for_bounded_and_unbounded_keys():
    unbounded = profile(key(authorities=frozenset()))
    unbounded.verify(
        issuer="Official Issuer", version=signed_version(unbounded), source_hash="a" * 64
    )
    bounded = profile(key(valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31)))
    dated = VersionCreate(
        revision="1", authority=AuthorityClass.OFFICIAL_UA, effective_from=date(2026, 6, 1)
    )
    bounded.verify(
        issuer="Official Issuer",
        version=signed_version(bounded, dated),
        source_hash="a" * 64,
    )
