"""Один знімок корпусу на всю відповідь — і жодного мовчазного другого.

Відповідь читає корпус кілька разів: пошук, перевірка прольотів, аудит. Якщо ці читання
підуть до РІЗНИХ знімків, цитата може посилатись на стан, якого вже немає, а сторож
цього не побачить: обидва читання «успішні». `_resolve_snapshot_reader` існує рівно щоб
такого не сталось, і його відмови — це межа, а не зручність.

Виміряно 08.09.2026: гілкове покриття модуля 0.143 при дванадцяти непокритих ребрах.
Найнижче в дереві. Кожна з відмов нижче була непройденою.
"""

from __future__ import annotations

import pytest
from korpus.application.answer_snapshot import (
    SnapshotAnswerRuntime,
    SnapshotAuditPolicy,
    _resolve_snapshot_reader,
)
from korpus.application.snapshot_retrieval import SnapshotBoundRetriever


class _Reader:
    """Читач знімка. Тотожність важлива: правило про ОДИН читач, не про один тип."""

    def __init__(self, name: str) -> None:
        self.name = name

    def validate(self, *args: object, **kwargs: object) -> None:
        return None


class _PlainRetriever:
    """Ретривер БЕЗ власного читача — його треба обгорнути, а не пустити як є."""

    def search(self, *args: object, **kwargs: object) -> list[object]:
        return []


class _BoundRetriever(_PlainRetriever):
    def __init__(self, reader: _Reader) -> None:
        self.snapshot_reader = reader


class _Repository:
    def __init__(self, reader: _Reader | None = None) -> None:
        if reader is not None:
            self.corpus_snapshot_reader = reader


def _policy() -> SnapshotAuditPolicy:
    return SnapshotAuditPolicy(
        minimum_score=0.25,
        minimum_query_coverage=0.5,
        minimum_support_score=0.25,
        calibration_id="test-calibration",
    )


def test_no_snapshot_reader_anywhere_is_refused() -> None:
    """Немає знімка — немає лінеаризації. Відповідь без неї не будується взагалі."""
    with pytest.raises(ValueError, match="corpus snapshot reader is required"):
        _resolve_snapshot_reader(_Repository(), _PlainRetriever(), None)  # type: ignore[arg-type]


def test_two_different_readers_are_refused() -> None:
    """Два читачі — два знімки, і різниця між ними невидима у вироку.

    Саме тому правило про ТОТОЖНІСТЬ, а не про наявність: обидва об'єкти валідні
    поодинці, і кожне читання окремо виглядає успішним.
    """
    with pytest.raises(ValueError, match="share one corpus snapshot reader"):
        _resolve_snapshot_reader(
            _Repository(_Reader("repository")),  # type: ignore[arg-type]
            _BoundRetriever(_Reader("retriever")),  # type: ignore[arg-type]
            None,
        )


def test_the_same_reader_reached_by_two_paths_is_accepted() -> None:
    """Негативний контроль: правило карає РОЗБІЖНІСТЬ, а не наявність двох посилань."""
    shared = _Reader("shared")
    resolved = _resolve_snapshot_reader(
        _Repository(shared),  # type: ignore[arg-type]
        _BoundRetriever(shared),  # type: ignore[arg-type]
        shared,  # type: ignore[arg-type]
    )
    assert resolved is shared


def test_an_explicit_reader_alone_is_enough() -> None:
    resolved = _resolve_snapshot_reader(
        _Repository(),
        _PlainRetriever(),
        _Reader("explicit"),  # type: ignore[arg-type]
    )
    assert isinstance(resolved, _Reader)


def test_a_retriever_without_its_own_reader_is_bound_to_the_resolved_one() -> None:
    """Ретривер без знімка не пускається як є — його прив'язують до вирішеного читача.

    Інакше пошук ходив би повз лінеаризацію, а решта відповіді — крізь неї.
    """
    shared = _Reader("shared")
    runtime = SnapshotAnswerRuntime(
        repository=_Repository(shared),  # type: ignore[arg-type]
        retriever=_PlainRetriever(),  # type: ignore[arg-type]
        audit_policy=_policy(),
    )
    assert isinstance(runtime.retriever, SnapshotBoundRetriever)
    assert runtime.snapshot_reader is shared


def test_a_retriever_that_already_carries_a_reader_is_used_directly() -> None:
    """Негативний контроль до обгортання: подвійна обгортка — теж два шляхи до знімка."""
    shared = _Reader("shared")
    runtime = SnapshotAnswerRuntime(
        repository=_Repository(shared),  # type: ignore[arg-type]
        retriever=_BoundRetriever(shared),  # type: ignore[arg-type]
        audit_policy=_policy(),
    )
    assert not isinstance(runtime.retriever, SnapshotBoundRetriever)
    assert runtime.retriever.snapshot_reader is shared  # type: ignore[attr-defined]
