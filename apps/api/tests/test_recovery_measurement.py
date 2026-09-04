"""A recovery drill either measured something or it did not.

The runbook has asked for restore duration "against the declared RTO" since v5, and
until 2026-08-05 the only thing recorded was that pg_restore exited zero. A restore
that takes six hours passes that check.

These tests state the boundary the classifier draws: what counts as a measurement,
what counts as provenance, and — the one that matters — that a report cannot declare
itself to be about production by changing a string. That is not a hypothetical: the
same substitution happened in TEVV, where a calibration figure from a fixture was
reported as if it came from the corpus.
"""

from __future__ import annotations

from typing import Any

import pytest
from korpus.application.recovery import (
    FIXTURE_SCALE,
    INCOMPLETE_PROVENANCE,
    MEASURED,
    MISSING,
    OVERSTATED_SCALE,
    PRODUCTION_LIKE_MINIMUM_ROWS,
    UNEXPLAINED_LOSS,
    classify_recovery,
)


def _report(**overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "scale_class": "ci-fixture",
        "rto_seconds": 12.5,
        "rpo_seconds": 0.0,
        "lost_events": 0,
        "lost_documents_total": 0,
        # Ідентифікована частина втрати: рядки, які навчання створило й упізнає.
        "lost_documents": 0,
        "provenance": {
            "backup_bytes": 40960,
            "plaintext_bytes": 131072,
            "document_rows": 2,
            "audit_event_rows": 7,
            "engine_version": "170004",
            "measured_at": "2026-08-05T09:00:00+00:00",
            "writes_after_backup": 5,
        },
    }
    report.update(overrides)
    return report


def test_no_report_is_not_a_pass() -> None:
    """Every release assembled before today was assembled in exactly this state."""
    for absent in (None, {}):
        verdict = classify_recovery(absent)
        assert verdict.status == MISSING
        assert not verdict.executed
        assert not verdict.provenance_complete


@pytest.mark.parametrize(
    "field", ["backup_bytes", "document_rows", "engine_version", "measured_at"]
)
def test_a_duration_without_provenance_is_not_a_measurement(field: str) -> None:
    """12.5 seconds to restore what, from how much, on which engine version."""
    provenance = {k: v for k, v in _report()["provenance"].items() if k != field}
    verdict = classify_recovery(_report(provenance=provenance))
    assert verdict.status == INCOMPLETE_PROVENANCE
    assert field in verdict.reasons[0]
    assert verdict.executed and not verdict.provenance_complete


def test_a_report_with_no_duration_is_incomplete() -> None:
    assert classify_recovery(_report(rto_seconds=None)).status == INCOMPLETE_PROVENANCE
    assert classify_recovery(_report(rto_seconds="soon")).status == INCOMPLETE_PROVENANCE
    assert classify_recovery(_report(rto_seconds=-1)).status == INCOMPLETE_PROVENANCE


def test_an_unrecognised_scale_class_is_not_believed() -> None:
    for declared in ("", "production", "prod-ish", None):
        assert classify_recovery(_report(scale_class=declared)).status == INCOMPLETE_PROVENANCE


def test_a_fixture_cannot_promote_itself_by_editing_a_string() -> None:
    """Two rows and 128 KB do not become the operational corpus by being labelled so."""
    verdict = classify_recovery(_report(scale_class="production-like"))
    assert verdict.status == OVERSTATED_SCALE
    assert not verdict.scale_not_overstated
    assert "below the floor" in verdict.reasons[0]


def test_an_honest_fixture_report_is_accepted_and_still_says_what_it_is_not() -> None:
    verdict = classify_recovery(_report())
    assert verdict.status == FIXTURE_SCALE
    assert verdict.executed and verdict.provenance_complete and verdict.scale_not_overstated
    assert "does not transfer" in verdict.reasons[0]


def test_a_production_scale_claim_is_allowed_once_the_provenance_carries_it() -> None:
    """Allowed, not endorsed: whether the corpus is representative is §2.6 and §2.9."""
    provenance = _report()["provenance"] | {"document_rows": PRODUCTION_LIKE_MINIMUM_ROWS}
    verdict = classify_recovery(_report(scale_class="production-like", provenance=provenance))
    assert verdict.status == MEASURED
    assert verdict.reasons == ()


def test_zero_loss_without_writes_after_the_backup_is_not_a_measurement() -> None:
    """A copy of a database nobody wrote to loses nothing however broken the restore.

    The first version of the CI drill measured exactly this: it reported lost_events=0
    against a database whose last write preceded the backup. The number was true and
    said nothing, which is the failure mode this repository keeps finding.
    """
    provenance = _report()["provenance"] | {"writes_after_backup": 0}
    verdict = classify_recovery(_report(provenance=provenance))
    assert verdict.status == INCOMPLETE_PROVENANCE
    assert "trivially zero" in verdict.reasons[0]
    assert not verdict.provenance_complete


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_recovery_duration_is_not_a_measurement(bad: float) -> None:
    assert classify_recovery(_report(rto_seconds=bad)).status == INCOMPLETE_PROVENANCE
    assert classify_recovery(_report(rpo_seconds=bad)).status == INCOMPLETE_PROVENANCE


@pytest.mark.parametrize(
    "field",
    ["backup_bytes", "plaintext_bytes", "document_rows", "audit_event_rows", "writes_after_backup"],
)
def test_recovery_provenance_counts_are_discrete_and_finite(field: str) -> None:
    for bad in (True, 1.5, float("inf"), -1):
        provenance = _report()["provenance"] | {field: bad}
        assert classify_recovery(_report(provenance=provenance)).status == INCOMPLETE_PROVENANCE


@pytest.mark.parametrize("bad", [True, 1.5, float("inf"), -1])
def test_lost_event_count_is_a_nonnegative_integer(bad: object) -> None:
    assert classify_recovery(_report(lost_events=bad)).status == INCOMPLETE_PROVENANCE


# Виміряно 04.09.2026 незалежним верифікатором: `lost_events`, `lost_documents` і
# `lost_documents_total` вимірювались, друкувались і НЕ СУДИЛИСЬ ніким. Відновлення, що
# втратило п'ять тисяч документів, і бездоганне відновлення отримували ОДИН вирок, бо
# `recovery_numeric_problem` питає лише форму числа. Форма без порога — опис, не умова.


def test_loss_beyond_the_identified_fixture_is_refused() -> None:
    """Поріг не «нуль втрат» і не РОЗМІР вікна: судиться надлишок понад УПІЗНАНЕ."""
    verdict = classify_recovery(_report(lost_documents_total=6, lost_documents=5))
    assert verdict.status == UNEXPLAINED_LOSS
    assert not verdict.loss_explained
    assert "яких навчання не створювало" in verdict.reasons[0]


def test_loss_equal_to_the_identified_fixture_is_what_the_drill_is_for() -> None:
    """Втратити рівно ті рядки, які навчання створило, — задум, а не вада."""
    verdict = classify_recovery(_report(lost_documents_total=5, lost_documents=5))
    assert verdict.loss_explained
    assert verdict.status != UNEXPLAINED_LOSS


def test_corpus_loss_inside_the_window_size_is_still_unexplained() -> None:
    """П'ятий контрприклад верифікатора: ТОТОЖНІСТЬ, а не потужність.

    Дозвіл виданий на КОНКРЕТНУ множину рядків, які навчання створило після бекапу.
    Порівняння з РОЗМІРОМ вікна пропускало втрату до 4999 справжніх документів корпусу,
    бо число «влазило в дозволений розмір». Обслуговуваний корпус має 256 документів —
    він міг зникнути ЦІЛКОМ, а вирок лишався б «виміряно».
    """
    report = _report(lost_documents_total=3000, lost_documents=0)
    report["provenance"]["writes_after_backup"] = 5000
    verdict = classify_recovery(report)
    assert verdict.status == UNEXPLAINED_LOSS, "втрата корпусу всередині розміру вікна"
    assert "3000" in verdict.reasons[0]


def test_an_unmeasured_identified_loss_is_not_zero() -> None:
    """Без упізнаної частини не видно, що з утраченого пояснене — і це не нуль."""
    report = _report()
    del report["lost_documents"]
    assert classify_recovery(report).status == UNEXPLAINED_LOSS


def test_an_unmeasured_total_loss_is_not_zero() -> None:
    """Відсутнє поле — не нуль. Нуль тут був би згодою, якої ніхто не давав."""
    report = _report()
    del report["lost_documents_total"]
    verdict = classify_recovery(report)
    assert verdict.status == UNEXPLAINED_LOSS
    assert not verdict.loss_explained


def test_a_lost_audit_event_is_never_explained() -> None:
    """Навчання не пише подій після бекапу, тож будь-яка їх втрата не має пояснення."""
    verdict = classify_recovery(_report(lost_events=1))
    assert verdict.status == UNEXPLAINED_LOSS


def test_the_verdict_moves_when_the_loss_moves() -> None:
    """Дуал: вирок, який не рухається від входу, не є виміром цього входу.

    Саме цей стан і був вадою — два звіти з різницею в п'ять тисяч документів давали
    той самий рядок.
    """
    clean = classify_recovery(_report(lost_documents_total=0))
    lossy = classify_recovery(_report(lost_documents_total=5000, lost_events=500))
    assert clean.status != lossy.status
    assert clean.loss_explained and not lossy.loss_explained
