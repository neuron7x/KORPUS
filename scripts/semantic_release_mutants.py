"""First-order mutants for semantic corpus release identity (#26)."""
from __future__ import annotations

from snapshot_mutants import Mutant

DIGEST_CONTROL = (
    "apps/api/tests/test_corpus_snapshot_contract.py::"
    "test_release_identity_digest_commits_every_member_field"
)


def _digest(mutant_id: str, field: str, claim: str) -> Mutant:
    old = f"        _frame(digest, member.{field})\n"
    new = f'        _frame(digest, "{field}-omitted")\n'
    return Mutant(
        mutant_id,
        "apps/api/src/korpus/application/corpus_snapshot.py",
        old,
        new,
        DIGEST_CONTROL,
        claim,
    )


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
    Mutant(
        "TS47",
        "apps/api/src/korpus/infrastructure/semantic_release.py",
        '                canonical_title=str(row["canonical_title"]),\n',
        '                canonical_title="title-omitted",\n',
        "apps/api/tests/test_release_semantic_identity.py::"
        "test_answer_visible_title_change_changes_release_without_changing_evidence",
        "semantic projection carries the answer-visible title into release identity",
    ),
    Mutant(
        "TS48",
        "apps/api/src/korpus/infrastructure/semantic_release.py",
        '                authority=str(row["authority"]),\n',
        '                authority="authority-omitted",\n',
        "apps/api/tests/test_release_semantic_identity.py::"
        "test_ranking_authority_change_changes_release_without_changing_evidence",
        "semantic projection carries ranking authority into release identity",
    ),
    Mutant(
        "TS49",
        "apps/api/src/korpus/infrastructure/semantic_release.py",
        "                visibility_compartments=canonical_set(visibility[document_id]),\n",
        "                visibility_compartments=canonical_set(()),\n",
        "apps/api/tests/test_release_semantic_identity.py::"
        "test_visibility_compartment_change_changes_release_while_member_remains_visible",
        "semantic projection commits the relational compartment predicate state",
    ),
)
