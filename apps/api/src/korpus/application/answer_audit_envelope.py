"""Stable request-level fields embedded in every completed-answer audit event."""

from __future__ import annotations

import hashlib

from korpus import __version__
from korpus.application.policy_evidence import answer_policy_decision_id
from korpus.application.request_audit_context import current_request_audit_context
from korpus.domain.models import Identity, QueryRequest


def answer_request_envelope(identity: Identity, query: QueryRequest) -> dict[str, object]:
    context = current_request_audit_context()
    return {
        "policy_decision_id": answer_policy_decision_id(identity, query.corpus_ids),
        "session_binding": context.session_binding,
        "client_version": context.client_version,
        "service_version": __version__,
        "offline_mode": context.offline_mode,
        "query_hash": hashlib.sha256(query.text.encode("utf-8")).hexdigest(),
    }
