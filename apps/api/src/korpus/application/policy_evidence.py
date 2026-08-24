"""Content-addressed identity for one successful answer authorization decision."""

from __future__ import annotations

import hashlib
import json

from korpus.domain.models import Identity


def answer_policy_decision_id(identity: Identity, requested: list[str]) -> str:
    """Hash the exact policy inputs/outcome after ``resolve_corpora`` has succeeded.

    This is an identifier for audit correlation, not a capability token and not an
    alternate authorization mechanism.  Requested corpora can be treated as permitted
    here only because callers invoke it after the fail-closed policy check succeeds.
    """
    permitted = sorted(requested) if requested else sorted(identity.corpora)
    record = {
        "schema": "korpus.answer-policy-decision.v1",
        "permission": "answer:read",
        "subject": identity.subject,
        "roles": sorted(identity.roles),
        "clearance": int(identity.clearance),
        "identity_corpora": sorted(identity.corpora),
        "compartments": sorted(identity.compartments),
        "requested_corpora": list(requested),
        "permitted_corpora": permitted,
        "allowed": True,
    }
    material = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "pd1:" + hashlib.sha256(material).hexdigest()
