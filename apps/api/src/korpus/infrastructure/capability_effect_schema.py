from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, Index, String, Table

from korpus.infrastructure.schema import metadata

# Capability side-effect state is authoritative product state, not an adapter cache. It
# therefore belongs to the canonical SQLAlchemy metadata used by create_schema, migration
# parity and production startup checks. Behaviour stays in capability_effect_ledger.py.
capability_effects = Table(
    "capability_effects",
    metadata,
    Column("subject_id", String(256), primary_key=True),
    Column("idempotency_key", String(256), primary_key=True),
    Column("binding_digest", String(71), nullable=False),
    Column("invocation_id", String(36), nullable=False),
    Column("capability_id", String(128), nullable=False),
    Column("capability_version", String(64), nullable=False),
    Column("logical_resource", String(512), nullable=False),
    Column("input_digest", String(71), nullable=False),
    Column("state", String(32), nullable=False),
    Column("provider_reference", String(512)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "state IN ('PENDING','COMMITTED','FAILED_KNOWN_NO_EFFECT','OUTCOME_UNKNOWN','RECONCILED')",
        name="ck_capability_effect_state",
    ),
)

Index(
    "ix_capability_effects_reconciliation",
    capability_effects.c.state,
    capability_effects.c.updated_at,
)
