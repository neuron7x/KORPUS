from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.engine import Engine

from korpus.infrastructure.capability_effect_ledger import SqlEffectLedger
from korpus.infrastructure.capability_effect_schema import capability_effects
from korpus.infrastructure.repository import SCHEMA_REVISION, metadata

MIGRATION = Path("apps/api/migrations/versions/0024_capability_effect_ledger.py")


class _Dialect:
    name = "postgresql"


class _PostgresEngineWithoutConnection:
    dialect = _Dialect()


def test_capability_effects_share_canonical_repository_metadata() -> None:
    assert capability_effects.metadata is metadata
    assert metadata.tables["capability_effects"] is capability_effects
    assert "ix_capability_effects_reconciliation" in {
        index.name for index in capability_effects.indexes
    }


def test_postgres_effect_ledger_refuses_composition_without_identity_binder() -> None:
    engine = cast(Engine, cast(Any, _PostgresEngineWithoutConnection()))

    with pytest.raises(ValueError, match="trusted subject identity binder"):
        SqlEffectLedger(engine)


def test_effect_migration_is_head_pinned_and_uses_nonforgeable_subject_rls() -> None:
    text = MIGRATION.read_text(encoding="utf-8")

    assert SCHEMA_REVISION == "0024_capability_effect_ledger"
    assert 'down_revision: str | None = "0023_evidence_search_vector"' in text
    assert "ALTER TABLE capability_effects FORCE ROW LEVEL SECURITY" in text
    assert "subject_id = public.korpus_rls_subject()" in text
    assert "current_setting(" not in text
    assert "CREATE POLICY capability_effect_delete" not in text


def test_effect_migration_is_additive_and_downgrade_removes_only_its_table() -> None:
    text = MIGRATION.read_text(encoding="utf-8")

    assert 'op.create_table(\n        "capability_effects"' in text
    assert 'op.drop_table("capability_effects")' in text
    assert "DROP TABLE documents" not in text
    assert "DROP TABLE audit_events" not in text
