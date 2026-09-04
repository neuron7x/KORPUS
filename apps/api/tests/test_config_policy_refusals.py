"""Відмови політики налаштувань, яких не викликав жоден прогін.

Вимір покриття гілок 04.09.2026. Усі три — про оголошення без підстави: вимога
підписів джерел без профілю довіри; калібрований режим без артефактів; профіль
калібрування без оголошеного дайджесту. Кожна з них дозволяє системі СТВЕРДЖУВАТИ
більше, ніж вона може показати.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest
from korpus.config_policy import _load_security_profiles, _validate_calibration


def _security_settings(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "entitlement_profile_path": None,
        "entitlement_profile_sha256": None,
        "source_trust_profile_path": None,
        "source_trust_profile_sha256": None,
        "require_source_signatures": False,
        "reviewer_registry_path": None,
        "reviewer_registry_sha256": None,
        "corpus_governance_profile_path": None,
        "corpus_governance_profile_sha256": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_requiring_source_signatures_without_a_trust_profile_is_refused() -> None:
    """Вимога підписів без профілю довіри — вимога без того, чим її перевіряти.

    Ввімкнена вимога виглядала б суворішою за вимкнену, а насправді не мала б
    жодного джерела істини: правило, яке нікому застосувати.
    """
    with pytest.raises(ValueError, match="source signatures require a source trust profile"):
        _load_security_profiles(_security_settings(require_source_signatures=True))


def test_not_requiring_signatures_needs_no_trust_profile() -> None:
    """Негативне плече: правило прив'язане до ВИМОГИ, а не до наявності профілю."""
    _load_security_profiles(_security_settings(require_source_signatures=False))


def _calibration_settings(tmp_path: pathlib.Path, **changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "answer_policy_mode": "calibrated",
        "calibration_profile_path": None,
        "calibration_dataset_path": None,
        "calibration_system_manifest_path": None,
        "calibration_evaluation_protocol_path": None,
        "calibration_profile_sha256": "",
        "semantic_retrieval_enabled": False,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_calibrated_mode_without_its_artifacts_is_refused(tmp_path: pathlib.Path) -> None:
    """Калібрований режим — це твердження про виміряну похибку.

    Без артефактів воно спиралось би ні на що, а назва режиму читалась би як
    доказ. Відмова називає, ЯКИХ саме артефактів бракує.
    """
    with pytest.raises(ValueError, match="calibration artifacts are missing"):
        _validate_calibration(_calibration_settings(tmp_path))


def test_a_declared_profile_without_a_digest_is_refused(tmp_path: pathlib.Path) -> None:
    """Профіль без оголошеного дайджесту — файл, який ніхто не зобов'язався не міняти.

    Артефакти на місці, шлях правильний — і жодної прив'язки до вмісту. Підміна
    профілю не залишила б сліду.
    """
    paths: dict[str, object] = {}
    for name in (
        "calibration_profile_path",
        "calibration_dataset_path",
        "calibration_system_manifest_path",
        "calibration_evaluation_protocol_path",
    ):
        target = tmp_path / f"{name}.json"
        target.write_text("{}", encoding="utf-8")
        paths[name] = target
    with pytest.raises(ValueError, match="calibration profile digest is required"):
        _validate_calibration(_calibration_settings(tmp_path, **paths))


def test_an_uncalibrated_mode_needs_no_artifacts_at_all(tmp_path: pathlib.Path) -> None:
    """Негативне плече: вимога стосується САМЕ каліброваного режиму."""
    _validate_calibration(_calibration_settings(tmp_path, answer_policy_mode="threshold"))
