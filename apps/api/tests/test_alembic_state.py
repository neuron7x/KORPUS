from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("alembic_state", ROOT / "scripts/alembic_state.py")
assert SPEC and SPEC.loader
alembic_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(alembic_state)


def test_expected_head_comes_from_alembic_metadata() -> None:
    assert alembic_state.expected_heads() == ("0009_reviewer_credentials",)


def test_missing_script_location_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingLocationConfig:
        def __init__(self, _: str) -> None:
            pass

        @staticmethod
        def get_main_option(_: str) -> None:
            return None

    monkeypatch.setattr(alembic_state, "Config", MissingLocationConfig)
    with pytest.raises(alembic_state.MigrationStateError, match="script_location is missing"):
        alembic_state.expected_heads()


def test_obsolete_revision_is_rejected() -> None:
    with pytest.raises(alembic_state.MigrationStateError, match="DB-01_SCHEMA_REVISION"):
        alembic_state.verify_revisions(["0003_infrastructure_hardening"])


def test_current_revision_is_accepted() -> None:
    assert alembic_state.verify_revisions(["current"], ["current"]) == ("current",)


@pytest.mark.parametrize(
    "actual, expected", [([], ["head"]), (["a", "b"], ["a"]), (["a"], ["a", "b"])]
)
def test_missing_multiple_or_unexpected_heads_fail_closed(actual, expected) -> None:
    with pytest.raises(alembic_state.MigrationStateError, match="DB-01_SCHEMA_REVISION"):
        alembic_state.verify_revisions(actual, expected)
