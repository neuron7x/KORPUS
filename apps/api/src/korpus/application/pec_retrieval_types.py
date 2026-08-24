"""Acyclic value and capability contracts for PEC retrieval orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from korpus.application.predictive_evidence_control import ControllerTrace
from korpus.application.query_plan import QueryPlan
from korpus.domain.models import Identity, RetrievedEvidence


@runtime_checkable
class SemanticControllableRetriever(Protocol):
    def semantic_available(self) -> bool: ...

    def search_with_semantic(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int = 8,
        *,
        semantic_enabled: bool,
    ) -> list[RetrievedEvidence]: ...


@dataclass(frozen=True, slots=True)
class PECSearchOutcome:
    retrieved: list[RetrievedEvidence]
    plan: QueryPlan
    trace: ControllerTrace | None
    early_abstain: bool = False
