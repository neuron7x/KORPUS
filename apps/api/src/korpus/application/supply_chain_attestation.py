from __future__ import annotations

import hashlib
from collections.abc import Mapping

SLSA_PROVENANCE_V1 = "https://slsa.dev/provenance/v1"
IN_TOTO_STATEMENT_V1 = "https://in-toto.io/Statement/v1"


def build_in_toto_statement(*, artifact_name: str, artifact_bytes: bytes, builder_id: str, source_uri: str, source_digest: str) -> dict[str, object]:
    if not artifact_name or not builder_id or not source_uri:
        raise ValueError("artifact_name, builder_id and source_uri are required")
    return {
        "_type": IN_TOTO_STATEMENT_V1,
        "subject": [{"name": artifact_name, "digest": {"sha256": hashlib.sha256(artifact_bytes).hexdigest()}}],
        "predicateType": SLSA_PROVENANCE_V1,
        "predicate": {
            "buildDefinition": {"buildType": "https://korpus.dev/build/v1", "resolvedDependencies": [{"uri": source_uri, "digest": {"sha256": source_digest}}]},
            "runDetails": {"builder": {"id": builder_id}},
        },
    }


def verify_in_toto_subject(statement: Mapping[str, object], *, artifact_name: str, artifact_bytes: bytes) -> bool:
    if statement.get("_type") != IN_TOTO_STATEMENT_V1 or statement.get("predicateType") != SLSA_PROVENANCE_V1:
        return False
    subject = statement.get("subject")
    if not isinstance(subject, list) or len(subject) != 1 or not isinstance(subject[0], Mapping):
        return False
    item = subject[0]
    digest = item.get("digest")
    return item.get("name") == artifact_name and isinstance(digest, Mapping) and digest.get("sha256") == hashlib.sha256(artifact_bytes).hexdigest()
