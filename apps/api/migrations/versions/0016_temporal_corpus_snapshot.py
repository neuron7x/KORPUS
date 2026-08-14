"""temporal corpus snapshot identity

Revision ID: 0016_temporal_corpus_snapshot
Revises: 0015_plan_pricing
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_temporal_corpus_snapshot"
down_revision: str | None = "0015_plan_pricing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen migration logic. Do not import the runtime digest helper here: changing future
# application code must not change what this historical migration computes on replay.
_EVIDENCE_DOMAIN = b"korpus-version-evidence-v1\0"
_EPOCH_TABLES = (
    "documents",
    "document_compartments",
    "document_versions",
    "evidence_spans",
    "span_embeddings",
)


def _frame(hasher: object, value: str) -> None:
    encoded = value.encode("utf-8")
    hasher.update(len(encoded).to_bytes(8, "big"))  # type: ignore[attr-defined]
    hasher.update(encoded)  # type: ignore[attr-defined]


def _version_evidence_digest(
    rows: Sequence[tuple[str, int, int | None, str | None, str, str]],
) -> str:
    normalized = sorted(rows, key=lambda row: (row[1], row[0]))
    if not normalized:
        raise RuntimeError("approved legacy version has no evidence to seal")
    if len({row[0] for row in normalized}) != len(normalized):
        raise RuntimeError("approved legacy version has duplicate span ids")
    if len({row[1] for row in normalized}) != len(normalized):
        raise RuntimeError("approved legacy version has duplicate span ordinals")

    digest = hashlib.sha256()
    digest.update(_EVIDENCE_DOMAIN)
    for span_id, ordinal, page, section, text, text_hash in normalized:
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if text_hash != expected:
            raise RuntimeError("approved legacy evidence text_hash does not match text")
        _frame(digest, span_id)
        _frame(digest, str(ordinal))
        _frame(digest, "" if page is None else str(page))
        _frame(digest, "" if section is None else section)
        _frame(digest, text_hash)
    return digest.hexdigest()


def _backfill_evidence_digests() -> None:
    bind = op.get_bind()
    version_ids = bind.execute(
        sa.text("SELECT id FROM document_versions WHERE review_state = 'approved' ORDER BY id")
    ).scalars().all()
    for version_id in version_ids:
        mapped = bind.execute(
            sa.text(
                "SELECT id, ordinal, page, section, text, text_hash "
                "FROM evidence_spans WHERE version_id = :version_id ORDER BY ordinal, id"
            ),
            {"version_id": version_id},
        ).mappings().all()
        rows = [
            (
                str(row["id"]),
                int(row["ordinal"]),
                None if row["page"] is None else int(row["page"]),
                None if row["section"] is None else str(row["section"]),
                str(row["text"]),
                str(row["text_hash"]),
            )
            for row in mapped
        ]
        digest = _version_evidence_digest(rows)
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
    op.execute(
        "CREATE TRIGGER trg_approved_version_digest_immutable "
        "BEFORE UPDATE OF evidence_digest ON document_versions "
        "WHEN OLD.review_state = 'approved' AND NEW.evidence_digest IS NOT OLD.evidence_digest "
        "BEGIN SELECT RAISE(ABORT, 'approved evidence digest is immutable'); END"
    )


def _install_postgres_guards() -> None:
    # The application role has SELECT-only access to corpus_state_epoch so it cannot
    # forge snapshot validity. This migration-owned trigger function is therefore the
    # sole writer. SECURITY DEFINER is required for ordinary app writes to advance the
    # epoch; search_path is locked and the target table is schema-qualified.
    op.execute(
        """
        CREATE FUNCTION korpus_bump_corpus_state_epoch() RETURNS trigger AS $$
        BEGIN
          UPDATE public.corpus_state_epoch SET epoch = epoch + 1 WHERE singleton_id = 1;
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
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
    op.execute(
        """
        CREATE FUNCTION korpus_refuse_approved_digest_mutation() RETURNS trigger AS $$
        BEGIN
          IF OLD.review_state = 'approved'
             AND NEW.evidence_digest IS DISTINCT FROM OLD.evidence_digest THEN
            RAISE EXCEPTION 'approved evidence digest is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_approved_version_digest_immutable "
        "BEFORE UPDATE OF evidence_digest ON document_versions "
        "FOR EACH ROW EXECUTE FUNCTION korpus_refuse_approved_digest_mutation()"
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
        op.execute("DROP TRIGGER IF EXISTS trg_approved_version_digest_immutable")
        op.execute("DROP TRIGGER IF EXISTS trg_evidence_spans_immutable_update")
        op.execute("DROP TRIGGER IF EXISTS trg_evidence_spans_immutable_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_evidence_spans_immutable_insert")
        for table in _EPOCH_TABLES:
            for operation in ("insert", "update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_epoch_{operation}")
    elif dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_approved_version_digest_immutable ON document_versions"
        )
        op.execute("DROP FUNCTION IF EXISTS korpus_refuse_approved_digest_mutation()")
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
