"""Every way a detached source signature is rejected, exercised.

A controlled deployment requires `require_source_signatures`, which means an uploaded
version is admitted only if it carries an Ed25519 signature over its own metadata,
made by a key the trust profile knows, for the authority class that key is allowed to
sign, inside that key's validity interval, and not revoked.

Coverage recorded eleven of those branches as never taken. Each is a reason to refuse
provenance, and a refusal nothing has ever performed is a refusal on paper: the system
would admit the document and record that it verified it.

The signature here is real — Ed25519 over the canonical payload the verifier builds —
so a mistake in the payload construction fails these tests rather than passing them
with a mocked verifier that would agree with anything.
"""

from __future__ import annotations

import base64
from datetime import date

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from korpus.domain.models import AuthorityClass, VersionCreate
from korpus.security.source_authenticity import SourceTrustKey, SourceTrustProfile

ISSUER = "Test Issuer"
SOURCE_HASH = "c" * 64


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return private, base64.b64encode(raw).decode("ascii")


def _profile(**key_overrides: object) -> tuple[SourceTrustProfile, Ed25519PrivateKey]:
    private, public_b64 = _keypair()
    values: dict[str, object] = {
        "key_id": "official-key",
        "issuer": ISSUER,
        "public_key_b64": public_b64,
        "authorities": frozenset({AuthorityClass.OFFICIAL_UA}),
    }
    values.update(key_overrides)
    profile = SourceTrustProfile(
        profile_id="source-trust-test", keys={str(values["key_id"]): SourceTrustKey(**values)}
    )
    return profile, private


def _version(private: Ed25519PrivateKey | None, **overrides: object) -> VersionCreate:
    values: dict[str, object] = {
        "revision": "1",
        "authority": AuthorityClass.OFFICIAL_UA,
        "publication_date": date(2024, 6, 1),
        "source_key_id": "official-key",
    }
    values.update(overrides)
    unsigned = VersionCreate(**{**values, "source_signature_b64": "0" * 64})
    if private is None:
        return unsigned
    payload = SourceTrustProfile.signed_payload(
        issuer=ISSUER, version=unsigned, source_hash=SOURCE_HASH
    )
    signature = base64.b64encode(private.sign(payload)).decode("ascii")
    return VersionCreate(**{**values, "source_signature_b64": signature})


def test_a_correctly_signed_version_is_accepted() -> None:
    """The dual. Every refusal below is vacuous if nothing can be accepted."""
    profile, private = _profile()

    profile.verify(issuer=ISSUER, version=_version(private), source_hash=SOURCE_HASH)


def test_a_version_without_a_signature_is_refused() -> None:
    profile, _ = _profile()

    with pytest.raises(ValueError, match="detached source signature is required"):
        profile.verify(
            issuer=ISSUER,
            version=VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
            source_hash=SOURCE_HASH,
        )


def test_a_signature_from_an_unknown_key_is_refused() -> None:
    profile, private = _profile()

    with pytest.raises(ValueError, match="unknown or revoked"):
        profile.verify(
            issuer=ISSUER,
            version=_version(private, source_key_id="key-nobody-registered"),
            source_hash=SOURCE_HASH,
        )


def test_a_revoked_key_is_refused_even_though_the_signature_verifies() -> None:
    """Revocation is the case where the cryptography is fine and the answer is no."""
    profile, private = _profile(revoked=True)

    with pytest.raises(ValueError, match="unknown or revoked"):
        profile.verify(issuer=ISSUER, version=_version(private), source_hash=SOURCE_HASH)


def test_a_key_belonging_to_another_issuer_is_refused() -> None:
    profile, private = _profile(issuer="Some Other Ministry")

    with pytest.raises(ValueError, match="issuer mismatch"):
        profile.verify(issuer=ISSUER, version=_version(private), source_hash=SOURCE_HASH)


def test_a_key_not_authorised_for_the_declared_authority_class_is_refused() -> None:
    """A key that may sign internal drafts must not thereby sign official orders."""
    profile, private = _profile(authorities=frozenset({AuthorityClass.ANALYTICAL}))

    with pytest.raises(ValueError, match="not authorized for this authority class"):
        profile.verify(issuer=ISSUER, version=_version(private), source_hash=SOURCE_HASH)


def test_a_key_with_no_authority_restriction_signs_any_class() -> None:
    """The restriction is opt-in; an empty set must not mean "nothing allowed"."""
    profile, private = _profile(authorities=frozenset())

    profile.verify(issuer=ISSUER, version=_version(private), source_hash=SOURCE_HASH)


def test_a_signature_before_the_key_existed_is_refused() -> None:
    profile, private = _profile(valid_from=date(2025, 1, 1))

    with pytest.raises(ValueError, match="predates key validity"):
        profile.verify(
            issuer=ISSUER,
            version=_version(private, publication_date=date(2024, 6, 1)),
            source_hash=SOURCE_HASH,
        )


def test_a_signature_after_the_key_expired_is_refused() -> None:
    profile, private = _profile(valid_until=date(2024, 1, 1))

    with pytest.raises(ValueError, match="postdates key validity"):
        profile.verify(
            issuer=ISSUER,
            version=_version(private, publication_date=date(2024, 6, 1)),
            source_hash=SOURCE_HASH,
        )


def test_effective_from_stands_in_when_there_is_no_publication_date() -> None:
    """Which date is compared to the key's interval decides some refusals outright."""
    profile, private = _profile(valid_from=date(2025, 1, 1))

    with pytest.raises(ValueError, match="predates key validity"):
        profile.verify(
            issuer=ISSUER,
            version=_version(private, publication_date=None, effective_from=date(2024, 6, 1)),
            source_hash=SOURCE_HASH,
        )


def test_a_signature_over_a_different_source_hash_is_refused() -> None:
    """The signature binds the metadata to the bytes; swapping the bytes must fail."""
    profile, private = _profile()

    with pytest.raises(ValueError):
        profile.verify(issuer=ISSUER, version=_version(private), source_hash="d" * 64)


def test_a_signature_over_altered_metadata_is_refused() -> None:
    """Signing revision 1 and uploading revision 2 is the attack this prevents."""
    profile, private = _profile()
    signed = _version(private)
    tampered = signed.model_copy(update={"revision": "2"})

    with pytest.raises(ValueError):
        profile.verify(issuer=ISSUER, version=tampered, source_hash=SOURCE_HASH)


def test_a_public_key_of_the_wrong_length_is_refused() -> None:
    """Long enough to pass the field's length bound, wrong length as a key."""
    with pytest.raises(ValueError, match="must be 32 bytes"):
        SourceTrustKey(
            key_id="short",
            issuer=ISSUER,
            public_key_b64=base64.b64encode(b"x" * 48).decode("ascii"),
        )


def test_an_inverted_validity_interval_is_refused() -> None:
    _, public_b64 = _keypair()

    with pytest.raises(ValueError, match="validity interval is invalid"):
        SourceTrustKey(
            key_id="inverted",
            issuer=ISSUER,
            public_key_b64=public_b64,
            valid_from=date(2025, 1, 1),
            valid_until=date(2024, 1, 1),
        )


def test_a_profile_whose_map_disagrees_with_its_key_ids_is_refused() -> None:
    """Lookup is by map key; a disagreement means verifying against the wrong key."""
    _, public_b64 = _keypair()

    with pytest.raises(ValueError, match="does not match key_id"):
        SourceTrustProfile(
            profile_id="mismatched",
            keys={
                "map-name": SourceTrustKey(
                    key_id="different-name", issuer=ISSUER, public_key_b64=public_b64
                )
            },
        )


def test_an_empty_trust_profile_is_refused() -> None:
    """Requiring signatures against no keys would refuse everything, silently."""
    with pytest.raises(ValueError, match="requires at least one key"):
        SourceTrustProfile(profile_id="empty", keys={})
