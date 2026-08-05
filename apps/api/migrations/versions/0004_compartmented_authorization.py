"""compartmented need-to-know authorization

Revision ID: 0004_compartmented_authorization
Revises: 0003_infrastructure_hardening
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_compartmented_authorization"
down_revision: str | None = "0003_infrastructure_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Session-setting SQL fragments, named so the policy bodies below fit on one line.
# Each constant is the exact text it replaces; the emitted SQL is unchanged.
_CLEARANCE = "COALESCE(NULLIF(current_setting('korpus.clearance', true), ''), '-1')::int"
_CORPORA = "string_to_array(COALESCE(current_setting('korpus.corpora', true), ''), ',')"
_CLASSIFICATIONS = (
    "string_to_array(COALESCE(current_setting('korpus.classifications', true), ''), ',')"
)
_COMPARTMENTS = (
    "string_to_array(COALESCE(current_setting('korpus.compartments', true), ''), ',')"
)


def _roles() -> str:
    return "string_to_array(COALESCE(current_setting('korpus.roles', true), ''), ',')"


def _document_visible(alias: str = "documents") -> str:
    elements = f"jsonb_array_elements_text(COALESCE({alias}.compartments_json, '[]')::jsonb)"
    return f"""
        {alias}.access_tier <= {_CLEARANCE}
        AND {alias}.corpus_id = ANY({_CORPORA})
        AND {alias}.classification = ANY({_CLASSIFICATIONS})
        AND NOT EXISTS (
            SELECT 1
            FROM {elements} AS compartment(value)
            WHERE NOT (compartment.value = ANY({_COMPARTMENTS}))
        )
    """


def _writer() -> str:
    roles = _roles()
    return f"('admin' = ANY({roles}) OR 'curator' = ANY({roles}))"


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("compartments_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "document_compartments",
        sa.Column(
            "document_id",
            sa.String(length=36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("compartment", sa.String(length=64), primary_key=True),
    )
    op.create_index(
        "ix_document_compartments_compartment",
        "document_compartments",
        ["compartment", "document_id"],
    )

    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE document_compartments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_compartments FORCE ROW LEVEL SECURITY")

    for policy in ("document_delete", "document_update", "document_insert", "document_select"):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON documents")

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

    visible_compartment = (
        "EXISTS (SELECT 1 FROM documents d WHERE d.id = document_compartments.document_id)"
    )
    op.execute(
        "CREATE POLICY document_compartment_select ON document_compartments FOR SELECT USING "
        f"({visible_compartment})"
    )
    op.execute(
        "CREATE POLICY document_compartment_insert ON document_compartments FOR INSERT WITH CHECK "
        f"({_writer()} AND {visible_compartment})"
    )
    op.execute(
        "CREATE POLICY document_compartment_update ON document_compartments FOR UPDATE USING "
        f"({_writer()} AND {visible_compartment}) "
        f"WITH CHECK ({_writer()} AND {visible_compartment})"
    )
    op.execute(
        f"CREATE POLICY document_compartment_delete ON document_compartments FOR DELETE USING "
        f"('admin' = ANY({_roles()}) AND {visible_compartment})"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for policy in (
            "document_compartment_delete",
            "document_compartment_update",
            "document_compartment_insert",
            "document_compartment_select",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON document_compartments")
        op.execute("ALTER TABLE document_compartments DISABLE ROW LEVEL SECURITY")

        for policy in ("document_delete", "document_update", "document_insert", "document_select"):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON documents")

        legacy_visible = f"""
            documents.access_tier <= {_CLEARANCE}
            AND documents.corpus_id = ANY({_CORPORA})
            AND documents.classification = ANY({_CLASSIFICATIONS})
        """
        op.execute(
            f"CREATE POLICY document_select ON documents FOR SELECT USING ({legacy_visible})"
        )
        op.execute(
            "CREATE POLICY document_insert ON documents FOR INSERT WITH CHECK "
            f"({_writer()} AND {legacy_visible})"
        )
        op.execute(
            "CREATE POLICY document_update ON documents FOR UPDATE USING "
            f"({_writer()} AND {legacy_visible}) "
            f"WITH CHECK ({_writer()} AND {legacy_visible})"
        )
        op.execute(
            f"CREATE POLICY document_delete ON documents FOR DELETE USING "
            f"('admin' = ANY({_roles()}) AND {legacy_visible})"
        )

    op.drop_index("ix_document_compartments_compartment", table_name="document_compartments")
    op.drop_table("document_compartments")
    op.drop_column("documents", "compartments_json")
