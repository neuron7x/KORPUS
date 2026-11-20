"""Recognize exactly the two additive, capability-bound reviewer UPDATE policies.

This is a closed SQL language, not a general CREATE POLICY allowance. Existing grants
and trusted visibility predicates remain required in both old-row and new-row checks.
Quoted literal contents and case are preserved; only whitespace between tokens varies.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"'(?:''|[^'])*'|[A-Za-z_][A-Za-z_0-9]*|<=|::|[^\s]")
_VERSION = """
pg_catalog.has_column_privilege(CURRENT_USER, 'public.document_versions', 'review_state', 'UPDATE')
AND 'reviewer' = ANY(public.korpus_rls_roles())
AND EXISTS (SELECT 1 FROM public.documents AS d WHERE d.id = document_versions.document_id)
"""
_DOCUMENT = """
pg_catalog.has_column_privilege(CURRENT_USER, 'public.documents', 'access_tier', 'UPDATE')
AND 'reviewer' = ANY(public.korpus_rls_roles())
AND documents.access_tier <= public.korpus_rls_clearance()
AND documents.corpus_id = ANY(public.korpus_rls_corpora())
AND documents.classification = ANY(public.korpus_rls_classifications())
AND NOT EXISTS (
 SELECT 1 FROM pg_catalog.jsonb_array_elements_text(COALESCE(documents.compartments_json, '[]')::jsonb) AS compartment(value)
 WHERE NOT (compartment.value = ANY(public.korpus_rls_compartments()))
)
"""
_POLICIES = (
    ("reviewer_version_update", "document_versions", _VERSION),
    ("reviewer_document_tier_update", "documents", _DOCUMENT),
)
_PROVEN_TOKENS = tuple(
    _TOKEN.findall(
        f"CREATE POLICY {name} ON public.{table} AS PERMISSIVE FOR UPDATE TO PUBLIC "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )
    for name, table, predicate in _POLICIES
)


def reviewer_policy_is_expanding(statement: str) -> bool:
    """Admit only the complete reviewed forms; every other SQL token is a refusal."""
    return _TOKEN.findall(statement) in _PROVEN_TOKENS
