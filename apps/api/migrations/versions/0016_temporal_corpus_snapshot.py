"""temporal corpus snapshot identity

Revision ID: 0016_temporal_corpus_snapshot
Revises: 0015_plan_pricing
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from korpus.application.corpus_snapshot import version_evidence_digest

revision: str = "0016_temporal_corpus_snapshot"
down_revision: str | None = "0015_plan_pricing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EPOCH_TABLES = ("documents", "document_compartments", "document_versions", "evidence_spans")


def _backfill_evidence_digests() -> None:
    bind = op.get_bind()
    version_ids = bind.execute(
        sa.text("SELECT id FROM document_versions WHERE review_state = 'approved' ORDER BY id")
    ).scalars().all()
    for version_id in version_ids:
        rows = bind.execute(
            sa.text(
                "SELECT id, ordinal, page, section, text, text_hash "
                "FROM evidence_spans WHERE version_id = :version_id ORDER BY ordinal, id"
            ),
            {"version_id": version_id},
        ).mappings().all()
        digest = version_evidence_digest(
            (
                str(row["id"]),
                int(row["ordinal"]),
                None if row["page"] is None else int(row["page"]),
                None if row["section"] is None else str(row["section"]),
                str(row["text"]),
                str(row["text_hash"]),
            )
            for row in rows
        )
        bind.execute(
            sa.text("UPDATE document_versions SET evidence_digest = :digest WHERE id = :id"),
            {"digest": digest, "id": version_id},
        )


def _install_sqlite_guards() -> None:
    for table in _EPOCH_TABLES:
        for operation in ("INSERT", "UPDATE", "DELETE"):
            name = f"trg_{table}_epoch_{operation.lower()}"
            op.execute(
                f"CREATE TRIGGER {name} AFTER {operation} ON {table} BEGIN "
                "UPDATE corpus_state_epoch SET epoch = epoch + 1 WHERE singleton_id = 1; END"
            )
    op.execute(
        "CREATE TRIGGER trg_evidence_spans_immutable_insert "
        "BEFORE INSERT ON evidence_spans "
        "WHEN EXISTS (SELECT 1 FROM document_versions "
        "WHERE id = NEW.version_id AND review_state = 'approved') "
        "BEGIN SELECT RAISE(ABORT, 'approved evidence is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_evidence_spans_immutable_delete "
        "BEFORE DELETE ON evidence_spans "
        "WHEN EXISTS (SELECT 1 FROM document_versions "
        "WHERE id = OLD.version_id AND review_state = 'approved') "
        "BEGIN SELECT RAISE(ABORT, 'approved evidence is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_evidence_spans_immutable_update "
        "BEFORE UPDATE ON evidence_spans "
        "WHEN EXISTS (SELECT 1 FROM document_versions "
        "WHERE id IN (OLD.version_id, NEW.version_id) AND review_state = 'approved') "
        "BEGIN SELECT RAISE(ABORT, 'approved evidence is immutable'); END"
    )


def _install_postgres_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION korpus_bump_corpus_state_epoch() RETURNS trigger AS $$
        BEGIN
          UPDATE corpus_state_epoch SET epoch = epoch + 1 WHERE singleton_id = 1;
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in _EPOCH_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_epoch AFTER INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION korpus_bump_corpus_state_epoch()"
        )
    op.execute(
        """
        CREATE FUNCTION korpus_refuse_approved_evidence_mutation() RETURNS trigger AS $$
        DECLARE
          old_approved boolean := false;
          new_approved boolean := false;
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            SELECT EXISTS(
              SELECT 1 FROM document_versions WHERE id = OLD.version_id AND review_state = 'approved'
            ) INTO old_approved;
          END IF;
          IF TG_OP <> 'DELETE' THEN
            SELECT EXISTS(
              SELECT 1 FROM document_versions WHERE id = NEW.version_id AND review_state = 'approved'
            ) INTO new_approved;
          END IF;
          IF old_approved OR new_approved THEN
            RAISE EXCEPTION 'approved evidence is immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_evidence_spans_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON evidence_spans "
        "FOR EACH ROW EXECUTE FUNCTION korpus_refuse_approved_evidence_mutation()"
    )


def upgrade() -> None:
    op.add_column("document_versions", sa.Column("evidence_digest", sa.String(64)))
    op.create_table(
        "corpus_state_epoch",
        sa.Column("singleton_id", sa.Integer(), primary_key=True),
        sa.Column("epoch", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("singleton_id = 1", name="ck_corpus_state_epoch_singleton"),
        sa.CheckConstraint("epoch >= 0", name="ck_corpus_state_epoch_nonnegative"),
    )
    op.execute("INSERT INTO corpus_state_epoch(singleton_id, epoch) VALUES (1, 0)")
    _backfill_evidence_digests()
    with op.batch_alter_table("document_versions") as batch:
        batch.create_check_constraint(
            "ck_approved_version_evidence_digest",
            "review_state != 'approved' OR evidence_digest IS NOT NULL",
        )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _install_sqlite_guards()
    elif dialect == "postgresql":
        _install_postgres_guards()
    else:
        raise RuntimeError(f"unsupported migration dialect: {dialect}")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_evidence_spans_immutable_update")
        op.execute("DROP TRIGGER IF EXISTS trg_evidence_spans_immutable_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_evidence_spans_immutable_insert")
        for table in _EPOCH_TABLES:
            for operation in ("insert", "update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_epoch_{operation}")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_evidence_spans_immutable ON evidence_spans")
        op.execute("DROP FUNCTION IF EXISTS korpus_refuse_approved_evidence_mutation()")
        for table in _EPOCH_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_epoch ON {table}")
        op.execute("DROP FUNCTION IF EXISTS korpus_bump_corpus_state_epoch()")
    else:
        raise RuntimeError(f"unsupported migration dialect: {dialect}")

    with op.batch_alter_table("document_versions") as batch:
        batch.drop_constraint("ck_approved_version_evidence_digest", type_="check")
        batch.drop_column("evidence_digest")
    op.drop_table("corpus_state_epoch")
