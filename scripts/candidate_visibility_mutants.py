"""First-order mutants for candidate-admission equivalence (#27)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutant:
    id: str
    path: str
    old: str
    new: str
    replacements: int
    control: str
    claim: str


MUTANTS = (
    Mutant(
        "CV01",
        "apps/api/src/korpus/infrastructure/retrieval_queries.py",
        "AND (v.id, v.document_id) NOT IN (SELECT id, document_id FROM superseded)",
        "AND v.id NOT IN (SELECT id FROM superseded)",
        2,
        "apps/api/tests/test_candidate_visibility_equivalence.py::"
        "test_cross_document_supersession_cannot_remove_a_candidate",
        "candidate supersession is scoped to the predecessor's document",
    ),
    Mutant(
        "CV02",
        "apps/api/src/korpus/infrastructure/retrieval_queries.py",
        "              {compartment_clause}\n",
        "",
        2,
        "apps/api/tests/test_candidate_visibility_equivalence.py::"
        "test_invisible_compartment_rows_cannot_consume_candidate_budget",
        "need-to-know filtering occurs before candidate LIMIT",
    ),
    Mutant(
        "CV03",
        "apps/api/src/korpus/infrastructure/retrieval_queries.py",
        '        forbidden = f"AND dc.compartment NOT IN ({placeholders})"\n',
        '        forbidden = ""\n',
        1,
        "apps/api/tests/test_candidate_visibility_equivalence.py::"
        "test_assigned_compartment_is_admitted_but_partial_assignment_is_not",
        "assigned compartments remain admissible while partial assignment is refused",
    ),
)
