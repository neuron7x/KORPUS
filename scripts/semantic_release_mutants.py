"""First-order mutants for semantic corpus release identity (#26)."""
from __future__ import annotations

from snapshot_mutants import Mutant

DIGEST_CONTROL = (
    "apps/api/tests/test_corpus_snapshot_contract.py::"
    "test_release_identity_digest_commits_every_member_field"
)
PROJECTION_CONTROL = (
    "apps/api/tests/test_release_semantic_identity.py::"
    "test_snapshot_release_equals_explicit_semantic_member_projection"
)
SOURCE = "apps/api/src/korpus/infrastructure/semantic_release.py"


def _digest(mutant_id: str, field: str, claim: str) -> Mutant:
    return Mutant(
        mutant_id,
        "apps/api/src/korpus/application/corpus_snapshot.py",
        f"        _frame(digest, member.{field})\n",
        f'        _frame(digest, "{field}-omitted")\n',
        DIGEST_CONTROL,
        claim,
    )


def _projection(
    mutant_id: str,
    old: str,
    new: str,
    claim: str,
) -> Mutant:
    return Mutant(mutant_id, SOURCE, old, new, PROJECTION_CONTROL, claim)


MUTANTS = (
    _digest("TS33", "canonical_title", "release identity commits citation title"),
    _digest("TS34", "corpus_id", "release identity commits corpus authorization semantics"),
    _digest("TS35", "access_tier", "release identity commits access and egress tier"),
    _digest("TS36", "classification", "release identity commits classification semantics"),
    _digest(
        "TS37",
        "document_compartments",
        "release identity commits materialized document compartment semantics",
    ),
    _digest(
        "TS38",
        "visibility_compartments",
        "release identity commits relational need-to-know semantics",
    ),
    _digest("TS39", "revision", "release identity commits citation revision"),
    _digest("TS40", "source_uri", "release identity commits citation source URI"),
    _digest("TS41", "publication_date", "release identity commits publication-time semantics"),
    _digest("TS42", "effective_from", "release identity commits lower currency bound"),
    _digest("TS43", "effective_until", "release identity commits upper currency bound"),
    _digest("TS44", "rescinded_at", "release identity commits rescission semantics"),
    _digest("TS45", "authority", "release identity commits ranking and eligibility authority"),
    _digest("TS46", "supersedes_version_id", "release identity commits supersession semantics"),
    _projection(
        "TS47",
        "                document_id=document_id,\n",
        '                document_id="document-omitted",\n',
        "semantic projection commits document identity",
    ),
    _projection(
        "TS48",
        '                version_id=str(row["version_id"]),\n',
        '                version_id="version-omitted",\n',
        "semantic projection commits version identity",
    ),
    _projection(
        "TS49",
        '                source_hash=str(row["source_hash"]),\n',
        '                source_hash="source-omitted",\n',
        "semantic projection commits source provenance",
    ),
    _projection(
        "TS50",
        '                review_state=str(row["review_state"]),\n',
        '                review_state="state-omitted",\n',
        "semantic projection commits review state",
    ),
    _projection(
        "TS51",
        "                evidence_digest=evidence_digest,\n",
        '                evidence_digest="evidence-omitted",\n',
        "semantic projection commits sealed evidence digest",
    ),
    _projection(
        "TS52",
        '                canonical_title=str(row["canonical_title"]),\n',
        '                canonical_title="title-omitted",\n',
        "semantic projection commits citation title",
    ),
    _projection(
        "TS53",
        '                corpus_id=str(row["corpus_id"]),\n',
        '                corpus_id="corpus-omitted",\n',
        "semantic projection commits corpus scope",
    ),
    _projection(
        "TS54",
        '                access_tier=str(int(row["access_tier"])),\n',
        '                access_tier="tier-omitted",\n',
        "semantic projection commits access tier",
    ),
    _projection(
        "TS55",
        '                classification=str(row["classification"]),\n',
        '                classification="classification-omitted",\n',
        "semantic projection commits classification",
    ),
    _projection(
        "TS56",
        "                document_compartments=_stored_compartments(\n"
        '                    row["compartments_json"]\n'
        "                ),\n",
        "                document_compartments=canonical_set(()),\n",
        "semantic projection commits materialized compartment state",
    ),
    _projection(
        "TS57",
        "                visibility_compartments=canonical_set(visibility[document_id]),\n",
        "                visibility_compartments=canonical_set(()),\n",
        "semantic projection commits relational compartment state",
    ),
    _projection(
        "TS58",
        '                revision=str(row["revision"]),\n',
        '                revision="revision-omitted",\n',
        "semantic projection commits citation revision",
    ),
    _projection(
        "TS59",
        '                source_uri=canonical_optional(row["source_uri"]),\n',
        "                source_uri=canonical_optional(None),\n",
        "semantic projection commits citation source URI",
    ),
    _projection(
        "TS60",
        '                publication_date=_optional_temporal(row["publication_date"]),\n',
        "                publication_date=canonical_optional(None),\n",
        "semantic projection commits publication date",
    ),
    _projection(
        "TS61",
        '                effective_from=_optional_temporal(row["effective_from"]),\n',
        "                effective_from=canonical_optional(None),\n",
        "semantic projection commits effective-from date",
    ),
    _projection(
        "TS62",
        '                effective_until=_optional_temporal(row["effective_until"]),\n',
        '                effective_until=canonical_optional("2099-01-01"),\n',
        "semantic projection commits effective-until date",
    ),
    _projection(
        "TS63",
        '                rescinded_at=_optional_temporal(row["rescinded_at"]),\n',
        '                rescinded_at=canonical_optional("2099-01-01"),\n',
        "semantic projection commits rescission state",
    ),
    _projection(
        "TS64",
        '                authority=str(row["authority"]),\n',
        '                authority="authority-omitted",\n',
        "semantic projection commits ranking authority",
    ),
    _projection(
        "TS65",
        "                supersedes_version_id=canonical_optional(\n"
        '                    row["supersedes_version_id"]\n'
        "                ),\n",
        "                supersedes_version_id=canonical_optional(None),\n",
        "semantic projection commits supersession semantics",
    ),
)
