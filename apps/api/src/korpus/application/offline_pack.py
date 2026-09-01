"""Fresh-policy, signed offline evidence packs.

An offline pack is not a second corpus authority.  Export re-runs online authorization,
freezes only currently retrievable spans, binds the exact corpus-release identity, and
signs the whole payload.  A pack that exceeds the configured bound is refused rather
than silently truncated.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Protocol

from korpus.application.corpus_snapshot import release_token
from korpus.application.policy import PolicyEngine
from korpus.application.policy_evidence import answer_policy_decision_id
from korpus.application.ports import Repository
from korpus.domain.models import (
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
)


class OfflinePackLimitError(RuntimeError):
    pass


class OfflinePackSigner(Protocol):
    key_id: str
    public_key_b64: str

    def sign_b64(self, payload: bytes) -> str: ...


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class OfflinePackService:
    def __init__(
        self,
        repository: Repository,
        policy: PolicyEngine,
        signer: OfflinePackSigner,
        *,
        ttl_seconds: int,
        max_spans: int,
    ) -> None:
        self.repository = repository
        self.policy = policy
        self.signer = signer
        self.ttl_seconds = ttl_seconds
        self.max_spans = max_spans

    def export(
        self, identity: Identity, requested_corpora: list[str], *, now: datetime | None = None
    ) -> dict[str, object]:
        issued = (now or datetime.now(UTC)).astimezone(UTC)
        corpora = self.policy.resolve_corpora(identity, requested_corpora)
        rows = self.repository.list_retrievable_spans(identity, corpora, issued.date())
        if len(rows) > self.max_spans:
            raise OfflinePackLimitError(
                f"offline pack contains {len(rows)} spans; configured maximum is {self.max_spans}"
            )
        rows.sort(key=lambda row: (str(row[1].id), str(row[2].id), row[0].ordinal, str(row[0].id)))
        release = release_token(self.repository, identity, corpora, issued.date()).release_id
        policy_id = answer_policy_decision_id(identity, requested_corpora)
        payload: dict[str, object] = {
            "schema": "korpus.offline-pack.v1",
            "algorithm": "Ed25519",
            "key_id": self.signer.key_id,
            "subject": identity.subject,
            "clearance": int(identity.clearance),
            "compartments": sorted(identity.compartments),
            "corpora": sorted(corpora),
            "policy_decision_id": policy_id,
            "corpus_release": release,
            "issued_at": issued.isoformat(),
            "valid_until": (issued + timedelta(seconds=self.ttl_seconds)).isoformat(),
            "revoked": False,
            "spans": [self._span_payload(*row) for row in rows],
        }
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        signed = {**payload, "payload_sha256": digest}
        material = canonical_json(signed).encode("utf-8")
        pack = {**signed, "signature": self.signer.sign_b64(material)}
        self.repository.append_audit(
            identity,
            "offline_pack.exported",
            "offline_pack",
            digest,
            {
                "payload_sha256": digest,
                "policy_decision_id": policy_id,
                "corpora": sorted(corpora),
                "corpus_release": release,
                "span_count": len(rows),
                "valid_until": pack["valid_until"],
                "key_id": self.signer.key_id,
            },
        )
        return pack

    @staticmethod
    def _span_payload(
        span: EvidenceSpanRecord,
        document: DocumentRecord,
        version: DocumentVersionRecord,
    ) -> dict[str, object]:
        return {
            "span_id": str(span.id),
            "version_id": str(version.id),
            "document_id": str(document.id),
            "title": document.canonical_title,
            "corpus_id": document.corpus_id,
            "access_tier": int(document.access_tier),
            "classification": document.classification.value,
            "revision": version.revision,
            "authority": version.authority.value,
            "source_hash": version.source_hash,
            "source_uri": version.source_uri,
            "publication_date": version.publication_date.isoformat()
            if version.publication_date
            else None,
            "effective_from": version.effective_from.isoformat()
            if version.effective_from
            else None,
            "effective_until": version.effective_until.isoformat()
            if version.effective_until
            else None,
            "rescinded_at": version.rescinded_at.isoformat() if version.rescinded_at else None,
            "ordinal": span.ordinal,
            "page": span.page,
            "section": span.section,
            "text": span.text,
            "text_hash": span.text_hash,
        }
