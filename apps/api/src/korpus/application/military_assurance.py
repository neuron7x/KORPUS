"""Fail-closed military knowledge assurance primitives.

The functions in this module deliberately avoid autonomous tactical reasoning. They make
knowledge delivery safer and more useful for training by verifying offline artifacts,
separating presentation level from source claims, and routing human corrections through
an immutable review queue rather than mutating corpus truth.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from enum import StrEnum

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, model_validator

from korpus.application.offline_pack import canonical_json


class OfflinePackState(StrEnum):
    VALID = "valid"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    REVOKED = "revoked"
    DIGEST_MISMATCH = "digest_mismatch"
    SIGNATURE_INVALID = "signature_invalid"
    SCHEMA_UNSUPPORTED = "schema_unsupported"


class OfflinePackVerification(BaseModel):
    model_config = ConfigDict(frozen=True)
    state: OfflinePackState
    usable: bool
    payload_sha256: str | None = None
    corpus_release: str | None = None
    valid_until: datetime | None = None


def verify_offline_pack(
    pack: dict[str, object],
    *,
    trusted_public_key_b64: str,
    now: datetime | None = None,
) -> OfflinePackVerification:
    """Verify integrity, signature and freshness before any offline knowledge is usable."""
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    if pack.get("schema") != "korpus.offline-pack.v1":
        return OfflinePackVerification(state=OfflinePackState.SCHEMA_UNSUPPORTED, usable=False)
    if bool(pack.get("revoked", False)):
        return OfflinePackVerification(state=OfflinePackState.REVOKED, usable=False)

    signature = pack.get("signature")
    declared_digest = pack.get("payload_sha256")
    if not isinstance(signature, str) or not isinstance(declared_digest, str):
        return OfflinePackVerification(state=OfflinePackState.DIGEST_MISMATCH, usable=False)

    unsigned_payload = {
        key: value for key, value in pack.items() if key not in {"signature", "payload_sha256"}
    }
    computed_digest = hashlib.sha256(canonical_json(unsigned_payload).encode("utf-8")).hexdigest()
    if computed_digest != declared_digest:
        return OfflinePackVerification(
            state=OfflinePackState.DIGEST_MISMATCH,
            usable=False,
            payload_sha256=declared_digest,
        )

    signed = {key: value for key, value in pack.items() if key != "signature"}
    try:
        public = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(trusted_public_key_b64, validate=True)
        )
        public.verify(
            base64.b64decode(signature, validate=True), canonical_json(signed).encode("utf-8")
        )
    except (ValueError, InvalidSignature):
        return OfflinePackVerification(
            state=OfflinePackState.SIGNATURE_INVALID,
            usable=False,
            payload_sha256=declared_digest,
        )

    issued = datetime.fromisoformat(str(pack["issued_at"])).astimezone(UTC)
    valid_until = datetime.fromisoformat(str(pack["valid_until"])).astimezone(UTC)
    if observed < issued:
        state = OfflinePackState.NOT_YET_VALID
        usable = False
    elif observed > valid_until:
        state = OfflinePackState.EXPIRED
        usable = False
    else:
        state = OfflinePackState.VALID
        usable = True
    return OfflinePackVerification(
        state=state,
        usable=usable,
        payload_sha256=declared_digest,
        corpus_release=str(pack.get("corpus_release"))
        if pack.get("corpus_release") is not None
        else None,
        valid_until=valid_until,
    )


class AudienceLevel(StrEnum):
    RECRUIT = "recruit"
    OPERATOR = "operator"
    NCO = "nco"
    OFFICER = "officer"
    INSTRUCTOR = "instructor"


class EvidenceClaim(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    source_binding_ids: frozenset[str] = Field(min_length=1, max_length=64)


class ExplanationEnvelope(BaseModel):
    """Presentation may change; licensed claims and evidence identities may not."""

    model_config = ConfigDict(frozen=True)
    audience: AudienceLevel
    claims: tuple[EvidenceClaim, ...] = Field(min_length=1, max_length=256)
    explanation: str = Field(min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def unique_claims(self) -> ExplanationEnvelope:
        ids = [item.id for item in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("explanation claim ids must be unique")
        return self


def presentation_equivalent(a: ExplanationEnvelope, b: ExplanationEnvelope) -> bool:
    """True only when audience adaptation preserves exact claim/evidence identity."""
    left = {(claim.id, tuple(sorted(claim.source_binding_ids))) for claim in a.claims}
    right = {(claim.id, tuple(sorted(claim.source_binding_ids))) for claim in b.claims}
    return left == right


class CorrectionKind(StrEnum):
    STALE_SOURCE = "stale_source"
    MISSING_SOURCE = "missing_source"
    INCORRECT_BINDING = "incorrect_binding"
    AMBIGUOUS_EXPLANATION = "ambiguous_explanation"
    OTHER = "other"


class ReviewState(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CorrectionSubmission(BaseModel):
    model_config = ConfigDict(frozen=True)
    reporter_subject: str = Field(min_length=1, max_length=200)
    kind: CorrectionKind
    document_id: str = Field(min_length=1, max_length=128)
    version_id: str = Field(min_length=1, max_length=128)
    span_id: str | None = Field(default=None, max_length=128)
    note: str = Field(min_length=3, max_length=4000)

    @property
    def fingerprint(self) -> str:
        material = "\x1f".join(
            [
                self.kind,
                self.document_id,
                self.version_id,
                self.span_id or "",
                " ".join(self.note.split()),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


class ReviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: ReviewState = ReviewState.OPEN
    report_count: int = Field(ge=1)
    reporter_subjects: tuple[str, ...] = Field(min_length=1)
    submission: CorrectionSubmission


def build_review_queue(submissions: list[CorrectionSubmission]) -> tuple[ReviewItem, ...]:
    """Deterministically deduplicate reports; never change corpus truth automatically."""
    grouped: dict[str, list[CorrectionSubmission]] = {}
    for item in submissions:
        grouped.setdefault(item.fingerprint, []).append(item)
    queue: list[ReviewItem] = []
    for fingerprint in sorted(grouped):
        items = grouped[fingerprint]
        canonical = min(items, key=lambda item: item.reporter_subject)
        queue.append(
            ReviewItem(
                fingerprint=fingerprint,
                report_count=len(items),
                reporter_subjects=tuple(sorted({item.reporter_subject for item in items})),
                submission=canonical,
            )
        )
    return tuple(queue)
