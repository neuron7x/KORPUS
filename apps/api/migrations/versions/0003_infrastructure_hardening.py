"""infrastructure hardening, schema invariants, and complete corpus RLS

Revision ID: 0003_infrastructure_hardening
Revises: 0002_database_defense_and_vectors
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_infrastructure_hardening"
down_revision: str | None = "0002_database_defense_and_vectors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Session-setting SQL fragments, named so the policy bodies below fit on one line.
# Each constant is the exact text it replaces; the emitted SQL is unchanged.
_CLEARANCE = "COALESCE(NULLIF(current_setting('korpus.clearance', true), ''), '-1')::int"
_CORPORA = "string_to_array(COALESCE(current_setting('korpus.corpora', true), ''), ',')"
_CLASSIFICATIONS = (
    "string_to_array(COALESCE(current_setting('korpus.classifications', true), ''), ',')"
)


def _roles() -> str:
    return "string_to_array(COALESCE(current_setting('korpus.roles', true), ''), ',')"


def _document_visible(alias: str = "documents") -> str:
    return f"""
        {alias}.access_tier <= {_CLEARANCE}
        AND {alias}.corpus_id = ANY({_CORPORA})
        AND {alias}.classification = ANY({_CLASSIFICATIONS})
    """


def _writer() -> str:
    roles = _roles()
    return f"('admin' = ANY({roles}) OR 'curator' = ANY({roles}))"


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    op.create_index(
        "uq_current_version_per_document",
        "document_versions",
        ["document_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current IS TRUE"),
    )
    op.create_index(
        "ix_document_versions_validity",
        "document_versions",
        ["document_id", "review_state", "effective_from", "effective_until"],
    )
    op.create_index(
        "ix_audit_anchor_outbox_pending",
        "audit_anchor_outbox",
        ["delivered_at", "created_at", "sequence"],
    )

    if dialect != "postgresql":
        return

    op.alter_column("audit_events", "sequence", existing_type=sa.Integer(), type_=sa.BigInteger())
    op.alter_column(
        "audit_anchor_outbox", "sequence", existing_type=sa.Integer(), type_=sa.BigInteger()
    )
    op.alter_column("audit_heads", "sequence", existing_type=sa.Integer(), type_=sa.BigInteger())
    op.create_check_constraint(
        "ck_version_effective_window",
        "document_versions",
        "effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from",
    )
    op.create_check_constraint(
        "ck_version_current_approved",
        "document_versions",
        "NOT is_current OR review_state = 'approved'",
    )

    # Replace the v2 span-only policies with a complete corpus boundary.
    for table in ("documents", "document_versions", "evidence_spans", "span_embeddings"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    for policy in (
        "evidence_span_delete",
        "evidence_span_update",
        "evidence_span_insert",
        "evidence_span_authorized_select",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON evidence_spans")

    op.execute(
        f"CREATE POLICY document_select ON documents FOR SELECT USING ({_document_visible()})"
    )
    op.execute(
        "CREATE POLICY document_insert ON documents FOR INSERT WITH CHECK "
        f"({_writer()} AND {_document_visible()})"
    )
    op.execute(
        "CREATE POLICY document_update ON documents FOR UPDATE USING "
        f"({_writer()} AND {_document_visible()}) "
        f"WITH CHECK ({_writer()} AND {_document_visible()})"
    )
    op.execute(
        f"CREATE POLICY document_delete ON documents FOR DELETE USING "
        f"('admin' = ANY({_roles()}) AND {_document_visible()})"
    )

    visible_version = (
        "EXISTS (SELECT 1 FROM documents d WHERE d.id = document_versions.document_id)"
    )
    op.execute(
        f"CREATE POLICY version_select ON document_versions FOR SELECT USING ({visible_version})"
    )
    op.execute(
        "CREATE POLICY version_insert ON document_versions FOR INSERT WITH CHECK "
        f"({_writer()} AND {visible_version})"
    )
    op.execute(
        "CREATE POLICY version_update ON document_versions FOR UPDATE USING "
        f"({_writer()} AND {visible_version}) "
        f"WITH CHECK ({_writer()} AND {visible_version})"
    )
    op.execute(
        f"CREATE POLICY version_delete ON document_versions FOR DELETE USING "
        f"('admin' = ANY({_roles()}) AND {visible_version})"
    )

    visible_span = """
        EXISTS (
            SELECT 1 FROM document_versions v
            JOIN documents d ON d.id = v.document_id
            WHERE v.id = evidence_spans.version_id
        )
    """
    op.execute(
        f"CREATE POLICY evidence_span_select ON evidence_spans FOR SELECT USING ({visible_span})"
    )
    op.execute(
        "CREATE POLICY evidence_span_insert ON evidence_spans FOR INSERT WITH CHECK "
        f"({_writer()} AND {visible_span})"
    )
    op.execute(
        "CREATE POLICY evidence_span_update ON evidence_spans FOR UPDATE USING "
        f"({_writer()} AND {visible_span}) "
        f"WITH CHECK ({_writer()} AND {visible_span})"
    )
    op.execute(
        f"CREATE POLICY evidence_span_delete ON evidence_spans FOR DELETE USING "
        f"('admin' = ANY({_roles()}) AND {visible_span})"
    )

    visible_embedding = """
        EXISTS (
            SELECT 1 FROM evidence_spans s
            JOIN document_versions v ON v.id = s.version_id
            JOIN documents d ON d.id = v.document_id
            WHERE s.id = span_embeddings.span_id
        )
    """
    op.execute(
        f"CREATE POLICY embedding_select ON span_embeddings FOR SELECT USING ({visible_embedding})"
    )
    op.execute(
        "CREATE POLICY embedding_insert ON span_embeddings FOR INSERT WITH CHECK "
        f"({_writer()} AND {visible_embedding})"
    )
    op.execute(
        "CREATE POLICY embedding_update ON span_embeddings FOR UPDATE USING "
        f"({_writer()} AND {visible_embedding}) "
        f"WITH CHECK ({_writer()} AND {visible_embedding})"
    )
    op.execute(
        f"CREATE POLICY embedding_delete ON span_embeddings FOR DELETE USING "
        f"('admin' = ANY({_roles()}) AND {visible_embedding})"
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table, policies in {
            "span_embeddings": (
                "embedding_delete",
                "embedding_update",
                "embedding_insert",
                "embedding_select",
            ),
            "evidence_spans": (
                "evidence_span_delete",
                "evidence_span_update",
                "evidence_span_insert",
                "evidence_span_select",
            ),
            "document_versions": (
                "version_delete",
                "version_update",
                "version_insert",
                "version_select",
            ),
            "documents": (
                "document_delete",
                "document_update",
                "document_insert",
                "document_select",
            ),
        }.items():
            for policy in policies:
                op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
            if table != "evidence_spans":
                op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

        # Restore the exact v2 span-only RLS boundary so downgrade is behaviorally valid.
        op.execute(
            f"""
            CREATE POLICY evidence_span_authorized_select ON evidence_spans FOR SELECT USING (
                EXISTS (
                    SELECT 1 FROM document_versions v
                    JOIN documents d ON d.id = v.document_id
                    WHERE v.id = evidence_spans.version_id
                      AND d.access_tier <= {_CLEARANCE}
                      AND d.corpus_id = ANY({_CORPORA})
                      AND d.classification = ANY({_CLASSIFICATIONS})
                )
            )
            """
        )
        roles = _roles()
        op.execute(
            "CREATE POLICY evidence_span_insert ON evidence_spans FOR INSERT WITH CHECK "
            f"('admin' = ANY({roles}) "
            f"OR 'curator' = ANY({roles}))"
        )
        op.execute(
            "CREATE POLICY evidence_span_update ON evidence_spans FOR UPDATE USING "
            f"('admin' = ANY({roles}) "
            f"OR 'curator' = ANY({roles})) "
            f"WITH CHECK ('admin' = ANY({roles}) "
            f"OR 'curator' = ANY({roles}))"
        )
        op.execute(
            "CREATE POLICY evidence_span_delete ON evidence_spans FOR DELETE USING "
            f"('admin' = ANY({roles}))"
        )
        op.drop_constraint("ck_version_current_approved", "document_versions", type_="check")
        op.drop_constraint("ck_version_effective_window", "document_versions", type_="check")
        op.alter_column(
            "audit_heads", "sequence", existing_type=sa.BigInteger(), type_=sa.Integer()
        )
        op.alter_column(
            "audit_anchor_outbox", "sequence", existing_type=sa.BigInteger(), type_=sa.Integer()
        )
        op.alter_column(
            "audit_events", "sequence", existing_type=sa.BigInteger(), type_=sa.Integer()
        )
    op.drop_index("ix_audit_anchor_outbox_pending", table_name="audit_anchor_outbox")
    op.drop_index("ix_document_versions_validity", table_name="document_versions")
    op.drop_index("uq_current_version_per_document", table_name="document_versions")
