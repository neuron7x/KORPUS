"""Родовід артефактів просування PEC: чотири гілки без жодного прогону.

Вимір покриття гілок 04.09.2026. Усі чотири — про відсутність, а не про розбіжність:
поле, якого в квитанції немає; профіль, чиї квитанції відтворення й навчання не ті;
вкладена прив'язка, що взагалі не є відображенням. Перевірка родоводу, яка мовчить
на відсутньому, підтверджує походження, якого ніхто не показував.
"""

from __future__ import annotations

import pytest
from korpus.application.controller_profile import (
    ControllerLeaf,
    ControllerProfile,
    ControllerRule,
)
from korpus.application.evidence_state import feature_schema_sha256
from korpus.application.pec_promotion_bindings import (
    _field_error,
    _flat_binding_errors,
    _nested_binding_errors,
)

DATASET = "1" * 64
PROTOCOL = "3" * 64
REPLAY = "4" * 64
TRAINING = "5" * 64
RELEASE = "b" * 64


def _profile() -> ControllerProfile:
    return ControllerProfile(
        profile_id="pec-binding-v1",
        dataset_sha256=DATASET,
        system_manifest_sha256="2" * 64,
        evaluation_protocol_sha256=PROTOCOL,
        replay_receipt_sha256=REPLAY,
        training_receipt_sha256=TRAINING,
        feature_schema_sha256=feature_schema_sha256(),
        corpus_release_id=RELEASE,
        answer_calibration_id="cal-v1",
        admission_status="PASS",
        controller_risk_limit=0.05,
        minimum_leaf_samples=30,
        rules=(
            ControllerRule(
                rule_id="recover",
                conditions=(),
                leaf=ControllerLeaf(
                    leaf_id="plan",
                    action="PLAN_QUERY_VARIANTS",
                    admitted=True,
                    observed_samples=100,
                    upper_error_bound=0.01,
                ),
            ),
        ),
    )


@pytest.mark.parametrize("receipt", [None, {}, {"dataset_sha256": ""}])
def test_a_field_that_is_absent_is_named_missing_not_mismatched(receipt: object) -> None:
    """Відсутнє й неправильне — різні діагнози.

    «Не збігається» каже, що артефакт є і не той; «немає» каже, що показувати нема
    чого. Злити їх в одне означає прийняти порожню квитанцію за пред'явлену.
    """
    error = _field_error(receipt, "training", "dataset_sha256", DATASET)  # type: ignore[arg-type]
    assert error == "binding_missing:training:dataset_sha256"


def test_a_field_that_is_present_and_wrong_is_named_a_mismatch() -> None:
    """Негативне плече: сторож мусить розрізняти два випадки, а не лише кричати."""
    error = _field_error({"dataset_sha256": "9" * 64}, "training", "dataset_sha256", DATASET)
    assert error == "binding_mismatch:training:dataset_sha256"
    assert _field_error({"dataset_sha256": DATASET}, "training", "dataset_sha256", DATASET) is None


def _receipts() -> dict[str, dict[str, object]]:
    return {
        "dataset_audit": {"dataset_sha256": DATASET},
        "counterfactual_replay": {
            "dataset_sha256": DATASET,
            "corpus_release_id": RELEASE,
            "evaluation_protocol_sha256": PROTOCOL,
            "answer_calibration_id": "cal-v1",
        },
        "training": {"dataset_sha256": DATASET, "oracle_sha256": "o" * 64},
        "oracle": {"replay_sha256": REPLAY},
        "controller_verify": {"profile_sha256": "p" * 64},
    }


def _files(**changes: str) -> dict[str, str]:
    files = {"counterfactual_replay": REPLAY, "training": TRAINING, "oracle": "o" * 64}
    files.update(changes)
    return files


def test_the_profile_must_name_the_replay_receipt_that_is_actually_on_disk() -> None:
    """Профіль несе хеш квитанції відтворення; файл на диску мусить бути ним же.

    Інакше профіль засвідчує один прогін, а просування спирається на інший.
    """
    errors = _flat_binding_errors(
        _profile(), _receipts(), _files(counterfactual_replay="9" * 64), "p" * 64
    )
    assert "binding_mismatch:profile:replay_receipt_sha256" in errors


def test_the_profile_must_name_the_training_receipt_that_is_actually_on_disk() -> None:
    errors = _flat_binding_errors(_profile(), _receipts(), _files(training="9" * 64), "p" * 64)
    assert "binding_mismatch:profile:training_receipt_sha256" in errors


def test_a_consistent_lineage_produces_no_errors() -> None:
    """Негативне плече: без нього два тести вище проходили б і на завжди-червоній перевірці."""
    assert _flat_binding_errors(_profile(), _receipts(), _files(), "p" * 64) == []


@pytest.mark.parametrize("receipt", [None, {}, {"binding": None}, {"binding": "не відображення"}])
def test_a_nested_binding_that_is_not_a_mapping_is_missing_not_empty(receipt: object) -> None:
    """Прив'язка, яку не можна прочитати як поля, — відсутня.

    Порожній перелік помилок тут означав би «перевірено, все гаразд», хоча не
    перевірено нічого: `all([])` істинне, і саме так відсутність стає дозволом.
    """
    errors = _nested_binding_errors(receipt, "training", {"dataset_sha256": DATASET})  # type: ignore[arg-type]
    assert errors == ["binding_missing:training:binding"]
