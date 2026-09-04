from __future__ import annotations

import threading
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectReservation,
    EffectState,
    InvalidEffectTransition,
    assert_effect_transition,
)

capability_effect_metadata = MetaData()

capability_effects = Table(
    "capability_effects",
    capability_effect_metadata,
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


class EffectLedgerConflict(RuntimeError):
    pass


class SqlEffectLedger:
    """Durable compare-and-set ledger for capability side effects.

    This module deliberately does not create its table at runtime. Production composition
    is invalid until the matching Alembic migration exists and the repository schema pin
    advances atomically. Tests may create `capability_effect_metadata` explicitly.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sqlite_lock = threading.RLock()

    def reserve(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        binding_digest: str,
        invocation_id: str,
        capability_id: str,
        capability_version: str,
        logical_resource: str,
        input_digest: str,
    ) -> EffectReservation:
        current = datetime.now(UTC)
        values = {
            "subject_id": subject_id,
            "idempotency_key": idempotency_key,
            "binding_digest": binding_digest,
            "invocation_id": invocation_id,
            "capability_id": capability_id,
            "capability_version": capability_version,
            "logical_resource": logical_resource,
            "input_digest": input_digest,
            "state": EffectState.PENDING.value,
            "provider_reference": None,
            "created_at": current,
            "updated_at": current,
        }
        guard = self._sqlite_lock if self.engine.dialect.name == "sqlite" else nullcontext()
        with guard:
            try:
                with self.engine.begin() as connection:
                    connection.execute(insert(capability_effects).values(**values))
                return EffectReservation(record=self._record(values), created=True)
            except IntegrityError:
                with self.engine.begin() as connection:
                    row = (
                        connection.execute(
                            select(capability_effects)
                            .where(capability_effects.c.subject_id == subject_id)
                            .where(capability_effects.c.idempotency_key == idempotency_key)
                        )
                        .mappings()
                        .first()
                    )
                if row is None:
                    raise
                return EffectReservation(record=self._record(row), created=False)

    def transition(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected: EffectState,
        target: EffectState,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        assert_effect_transition(expected, target)
        current = datetime.now(UTC)
        guard = self._sqlite_lock if self.engine.dialect.name == "sqlite" else nullcontext()
        with guard, self.engine.begin() as connection:
            changed = connection.execute(
                update(capability_effects)
                .where(capability_effects.c.subject_id == subject_id)
                .where(capability_effects.c.idempotency_key == idempotency_key)
                .where(capability_effects.c.state == expected.value)
                .values(
                    state=target.value,
                    provider_reference=provider_reference,
                    updated_at=current,
                )
            )
            if changed.rowcount != 1:
                row = (
                    connection.execute(
                        select(capability_effects)
                        .where(capability_effects.c.subject_id == subject_id)
                        .where(capability_effects.c.idempotency_key == idempotency_key)
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise EffectLedgerConflict("effect reservation does not exist")
                actual = EffectState(str(row["state"]))
                try:
                    assert_effect_transition(actual, target)
                except InvalidEffectTransition as exc:
                    raise EffectLedgerConflict(
                        f"effect transition changed concurrently: {actual.value} -> {target.value}"
                    ) from exc
                raise EffectLedgerConflict(
                    f"effect state changed concurrently: expected {expected.value}, got {actual.value}"
                )
            row = (
                connection.execute(
                    select(capability_effects)
                    .where(capability_effects.c.subject_id == subject_id)
                    .where(capability_effects.c.idempotency_key == idempotency_key)
                )
                .mappings()
                .one()
            )
        return self._record(row)

    def get(self, *, subject_id: str, idempotency_key: str) -> EffectRecord | None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(capability_effects)
                    .where(capability_effects.c.subject_id == subject_id)
                    .where(capability_effects.c.idempotency_key == idempotency_key)
                )
                .mappings()
                .first()
            )
        return self._record(row) if row is not None else None

    @staticmethod
    def _record(row: Any) -> EffectRecord:
        return EffectRecord(
            subject_id=str(row["subject_id"]),
            idempotency_key=str(row["idempotency_key"]),
            binding_digest=str(row["binding_digest"]),
            invocation_id=str(row["invocation_id"]),
            capability_id=str(row["capability_id"]),
            capability_version=str(row["capability_version"]),
            logical_resource=str(row["logical_resource"]),
            input_digest=str(row["input_digest"]),
            state=EffectState(str(row["state"])),
            provider_reference=(
                str(row["provider_reference"]) if row["provider_reference"] is not None else None
            ),
        )
