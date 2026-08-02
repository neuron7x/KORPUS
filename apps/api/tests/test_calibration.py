"""The calibrated threshold: loaded when sound, ignored — loudly — when not."""

from __future__ import annotations

import json
from pathlib import Path

from korpus.config import calibrated_threshold


def write(path: Path, payload: object) -> Path:
    target = path / "calibration.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_a_missing_file_means_the_code_default_stands(tmp_path: Path) -> None:
    assert calibrated_threshold(tmp_path / "absent.json") is None


def test_a_frozen_threshold_is_read(tmp_path: Path) -> None:
    assert calibrated_threshold(write(tmp_path, {"min_retrieval_score": 0.74})) == 0.74


def test_a_malformed_file_is_ignored_rather_than_fatal(tmp_path: Path) -> None:
    """A tuning file must not be able to keep the service from starting."""
    target = tmp_path / "calibration.json"
    target.write_text("{ this is not json", encoding="utf-8")
    assert calibrated_threshold(target) is None


def test_a_file_without_the_key_is_ignored(tmp_path: Path) -> None:
    assert calibrated_threshold(write(tmp_path, {"note": "wrong shape"})) is None


def test_a_non_numeric_threshold_is_ignored(tmp_path: Path) -> None:
    assert calibrated_threshold(write(tmp_path, {"min_retrieval_score": "high"})) is None


def test_an_out_of_range_threshold_is_ignored(tmp_path: Path) -> None:
    """A calibration that would answer everything is refused, not applied."""
    assert calibrated_threshold(write(tmp_path, {"min_retrieval_score": -1})) is None
    assert calibrated_threshold(write(tmp_path, {"min_retrieval_score": 7})) is None


def test_the_repository_calibration_is_present_and_sound() -> None:
    """The frozen file in the repository must itself satisfy the loader."""
    from korpus.config import CALIBRATION_FILE

    assert CALIBRATION_FILE.exists()
    value = calibrated_threshold()
    assert value is not None
    assert 0.0 < value <= 1.0
    record = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
    assert record["dataset_sha256"]
    assert record["cases"] == record["matched"], "frozen calibration must match every case"


def test_a_calibration_equal_to_the_default_changes_nothing(tmp_path: Path) -> None:
    """No log, no copy, no surprise: the same number is not a reconfiguration."""
    import korpus.config as config

    original = config.CALIBRATION_FILE
    config.CALIBRATION_FILE = write(tmp_path, {"min_retrieval_score": 0.72})
    try:
        config.get_settings.cache_clear()
        assert config.get_settings().min_retrieval_score == 0.72
    finally:
        config.CALIBRATION_FILE = original
        config.get_settings.cache_clear()


def test_the_frozen_calibration_actually_reaches_the_settings(tmp_path: Path) -> None:
    """The file is not decoration: a calibrated threshold governs what is served."""
    import korpus.config as config

    original = config.CALIBRATION_FILE
    config.CALIBRATION_FILE = write(tmp_path, {"min_retrieval_score": 0.81})
    try:
        config.get_settings.cache_clear()
        assert config.get_settings().min_retrieval_score == 0.81
    finally:
        config.CALIBRATION_FILE = original
        config.get_settings.cache_clear()
