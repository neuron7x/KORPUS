"""Сторожі профілю жорстких предикатів, яких не виконував жоден прогін.

Вимір покриття гілок 04.09.2026. Цей модуль читає `scripts/freeze_release_candidate.py`
— тобто його вирок вирішує, чи дерево має право стати кандидатом релізу. Сторож тут,
який ніколи не відмовляв, це сторож при воротах, які ніхто не пробував відчинити.

Спільна властивість усіх семи: вони відрізняють ОГОЛОШЕННЯ від ДОВЕДЕНОГО.
Виключення предиката, гейт, названий у профілі, прив'язка до релізу — кожне з них
можна просто написати, і кожне тут мусить бути звірене.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from korpus.application.production_hard_predicates import (
    _REQUIREMENTS,
    DISPOSITIONS,
    IN_RELEASE_PATH,
    NOT_IN_RELEASE_PATH,
    HardPredicateState,
    _exclusion_proved,
    _state,
    external_predicate_state,
    load_hard_predicate_profile,
)

ANY_ID = sorted(_REQUIREMENTS)[0]


def _state_value(**changes: object) -> HardPredicateState:
    values: dict[str, object] = {
        "predicate_id": ANY_ID,
        "gate": _REQUIREMENTS[ANY_ID].gate,
        "required_proof_class": "runtime",
        "software_ready": True,
        "externally_satisfied": True,
        "missing_software_artifacts": (),
        "failed_external_checks": (),
    }
    values.update(changes)
    return HardPredicateState(**values)  # type: ignore[arg-type]


def test_a_predicate_in_the_release_path_blocks_until_production_is_satisfied() -> None:
    """На дорозі в продакшен важить ВИКОНАНІСТЬ, а не оголошення."""
    assert _state_value(disposition=IN_RELEASE_PATH).blocks_candidate is False
    assert (
        _state_value(disposition=IN_RELEASE_PATH, externally_satisfied=False).blocks_candidate
        is True
    )


def test_an_excluded_predicate_blocks_until_the_exclusion_itself_is_proved() -> None:
    """Виключення теж мусить бути доведеним — інакше досить було б написати слово.

    `NOT_IN_RELEASE_PATH` із недоведеним виключенням БЛОКУЄ, хоч і оголошений поза
    дорогою: саме тут оголошення могло б підмінити доказ.
    """
    assert (
        _state_value(disposition=NOT_IN_RELEASE_PATH, disposition_proved=True).blocks_candidate
        is False
    )
    assert (
        _state_value(
            disposition=NOT_IN_RELEASE_PATH,
            disposition_proved=False,
            externally_satisfied=False,
        ).blocks_candidate
        is True
    )


def test_a_profile_with_an_unclassified_disposition_is_refused(tmp_path: pathlib.Path) -> None:
    """Предикат без ПРИДАТНОЇ диспозиції не має вироку — і не сміє мовчки дістати типовий.

    Невідоме слово в полі диспозиції прочиталось би як «щось із трьох», а насправді
    означає, що ніхто не сказав, чи цей предикат на дорозі в продакшен.
    """
    predicates = [
        {"id": name, "gate": _REQUIREMENTS[name].gate, "disposition": IN_RELEASE_PATH}
        for name in sorted(_REQUIREMENTS)
    ]
    predicates[0]["disposition"] = "ПОТІМ_РОЗБЕРЕМОСЬ"
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"predicates": predicates}), encoding="utf-8")
    with pytest.raises(ValueError, match="without a valid disposition"):
        load_hard_predicate_profile(path)


def test_a_profile_whose_dispositions_are_all_known_is_accepted(tmp_path: pathlib.Path) -> None:
    """Негативне плече: відмова вище не сміє бути правдою про кожен профіль."""
    predicates = [
        {"id": name, "gate": _REQUIREMENTS[name].gate, "disposition": IN_RELEASE_PATH}
        for name in sorted(_REQUIREMENTS)
    ]
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"predicates": predicates}), encoding="utf-8")
    assert set(DISPOSITIONS) >= {IN_RELEASE_PATH}
    assert load_hard_predicate_profile(path)["predicates"] == predicates


def test_a_gate_report_about_another_release_does_not_satisfy_this_one() -> None:
    """Звіт гейта прив'язаний до релізу, про який він.

    Без цієї прив'язки зелений звіт попереднього релізу задовольняв би предикат
    наступного: доказ був би справжній і НЕ ПРО ЦЕ дерево.
    """
    requirement = _REQUIREMENTS[ANY_ID]
    gates = {requirement.gate: {"release": "v0.9.6"}}
    satisfied, failed = external_predicate_state(ANY_ID, gates, current_release="v0.9.7")
    assert satisfied is False
    assert "gate_release_bound" in failed


@pytest.mark.parametrize(
    "raw",
    [
        {"gate": "redteam", "required_proof_class": "runtime", "software_artifacts": []},
        {"id": "x", "required_proof_class": "runtime", "software_artifacts": []},
        {"id": "x", "gate": "redteam", "software_artifacts": []},
        {"id": "x", "gate": "redteam", "required_proof_class": "runtime"},
    ],
)
def test_an_incomplete_predicate_record_is_refused(
    tmp_path: pathlib.Path, raw: dict[str, object]
) -> None:
    """Запис без ід, гейта, класу доказу або переліку артефактів не є предикатом.

    Кожне з цих полів — окреме твердження; відсутнє поле не має типового значення,
    бо типове значення тут було б чиєюсь думкою, вписаною замість доказу.
    """
    with pytest.raises(ValueError, match="invalid hard-predicate record"):
        _state(tmp_path, raw, {}, None, None)


def test_a_predicate_naming_a_gate_it_does_not_own_is_refused(tmp_path: pathlib.Path) -> None:
    """Дрейф гейта: профіль називає один гейт, оцінювач знає інший.

    Предикат тоді задовольнявся б звітом чужої перевірки — доказ існує, але не той.
    """
    raw = {
        "id": ANY_ID,
        "gate": "чужий-гейт",
        "required_proof_class": "runtime",
        "software_artifacts": [],
    }
    with pytest.raises(ValueError, match="gate drift"):
        _state(tmp_path, raw, {}, None, None)


def test_an_exclusion_without_a_named_key_is_not_proved(tmp_path: pathlib.Path) -> None:
    """Порожній ключ доказу виключення — це відсутність доказу, а не порожній доказ.

    Конверт нижче навмисно містить ПОРОЖНІЙ запис у `not_in_this_release`. Без
    раннього виходу порожній ключ предиката збігся б із ним, і предикат, який не
    назвав НІЧОГО, дістав би доведене виключення з дороги в продакшен. Тобто
    випадкова кома в топології звільняла б від доказу.
    """
    (tmp_path / "RELEASE_ENVELOPE.json").write_text(
        json.dumps(
            {
                "release_candidate": {
                    "deployment_topology": {"not_in_this_release": ["", "gcs_object_store"]}
                }
            }
        ),
        encoding="utf-8",
    )
    assert _exclusion_proved(tmp_path, {}) is False
    assert _exclusion_proved(tmp_path, {"not_in_release_path_proof": ""}) is False
    # Негативне плече: названий і справді виключений ключ мусить доводитись.
    assert _exclusion_proved(tmp_path, {"not_in_release_path_proof": "gcs_object_store"}) is True
    assert _exclusion_proved(tmp_path, {"not_in_release_path_proof": "інше"}) is False
