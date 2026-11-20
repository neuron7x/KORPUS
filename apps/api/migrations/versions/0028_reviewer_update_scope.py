"""Permit scoped reviewer updates through the existing review database capability.

Revision ID: 0028_reviewer_update_scope
Revises: 0027_learning_competency_integrity

Policies are additive and name-independent: roles are provisioned after migrations.
The column privilege is a login-capability discriminator, not a new column whitelist.
The existing populated-deployment retirement admission remains in force.
"""

from __future__ import annotations

from alembic import op

revision: str = "0028_reviewer_update_scope"
down_revision: str | None = "0027_learning_competency_integrity"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE POLICY reviewer_version_update ON public.document_versions
        AS PERMISSIVE FOR UPDATE TO PUBLIC
        USING (
          pg_catalog.has_column_privilege(CURRENT_USER, 'public.document_versions', 'review_state', 'UPDATE')
          AND 'reviewer' = ANY(public.korpus_rls_roles())
          AND EXISTS (SELECT 1 FROM public.documents AS d WHERE d.id = document_versions.document_id)
        )
        WITH CHECK (
          pg_catalog.has_column_privilege(CURRENT_USER, 'public.document_versions', 'review_state', 'UPDATE')
          AND 'reviewer' = ANY(public.korpus_rls_roles())
          AND EXISTS (SELECT 1 FROM public.documents AS d WHERE d.id = document_versions.document_id)
        )
        """
    )
    op.execute(
        """
        CREATE POLICY reviewer_document_tier_update ON public.documents
        AS PERMISSIVE FOR UPDATE TO PUBLIC
        USING (
          pg_catalog.has_column_privilege(CURRENT_USER, 'public.documents', 'access_tier', 'UPDATE')
          AND 'reviewer' = ANY(public.korpus_rls_roles())
          AND documents.access_tier <= public.korpus_rls_clearance()
          AND documents.corpus_id = ANY(public.korpus_rls_corpora())
          AND documents.classification = ANY(public.korpus_rls_classifications())
          AND NOT EXISTS (
            SELECT 1 FROM pg_catalog.jsonb_array_elements_text(COALESCE(documents.compartments_json, '[]')::jsonb) AS compartment(value)
            WHERE NOT (compartment.value = ANY(public.korpus_rls_compartments()))
          )
        )
        WITH CHECK (
          pg_catalog.has_column_privilege(CURRENT_USER, 'public.documents', 'access_tier', 'UPDATE')
          AND 'reviewer' = ANY(public.korpus_rls_roles())
          AND documents.access_tier <= public.korpus_rls_clearance()
          AND documents.corpus_id = ANY(public.korpus_rls_corpora())
          AND documents.classification = ANY(public.korpus_rls_classifications())
          AND NOT EXISTS (
            SELECT 1 FROM pg_catalog.jsonb_array_elements_text(COALESCE(documents.compartments_json, '[]')::jsonb) AS compartment(value)
            WHERE NOT (compartment.value = ANY(public.korpus_rls_compartments()))
          )
        )
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP POLICY reviewer_document_tier_update ON public.documents")
    op.execute("DROP POLICY reviewer_version_update ON public.document_versions")
