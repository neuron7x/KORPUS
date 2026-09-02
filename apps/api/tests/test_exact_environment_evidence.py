from __future__ import annotations

from korpus.application.exact_environment import exact_environment_state


def test_exact_environment_accepts_only_exact_lock_python_and_allowlist() -> None:
    checks, missing, mismatched, extras = exact_environment_state(
        {"a": "1", "b": "2"},
        {"a": "1", "b": "2", "pip": "26"},
        python_version="3.12.13",
        required_python="3.12.13",
        allowed_unmanaged={"pip"},
        hashes_complete=True,
    )
    assert all(checks.values()), checks
    assert not missing and not mismatched and not extras


def test_unmanaged_distribution_prevents_exact_environment_claim() -> None:
    checks, _, _, extras = exact_environment_state(
        {"a": "1"},
        {"a": "1", "rogue-import-hook": "9"},
        python_version="3.12.13",
        required_python="3.12.13",
        allowed_unmanaged=set(),
        hashes_complete=True,
    )
    assert checks["no_unmanaged_distributions"] is False
    assert extras == ["rogue-import-hook"]


def test_wrong_python_patch_version_prevents_exact_environment_claim() -> None:
    checks, *_ = exact_environment_state(
        {"a": "1"},
        {"a": "1"},
        python_version="3.12.12",
        required_python="3.12.13",
        allowed_unmanaged=set(),
        hashes_complete=True,
    )
    assert checks["production_python_exact"] is False


def test_missing_or_version_drift_remains_fail_closed() -> None:
    checks, missing, mismatched, _ = exact_environment_state(
        {"a": "1", "b": "2"},
        {"a": "9"},
        python_version="3.12.13",
        required_python="3.12.13",
        allowed_unmanaged=set(),
        hashes_complete=True,
    )
    assert checks["all_locked_components_installed"] is False and missing == ["b"]
    assert checks["all_versions_exact"] is False and mismatched["a"]["installed"] == "9"


def test_the_gate_has_a_state_in_which_it_can_be_green() -> None:
    """Гейт був НЕЗДІЙСНЕННИЙ за побудовою, і це виміряно 02.09.2026.

    Він читав ОБИДВА замки завжди й вимагав `production_python_exact` незалежно
    від того, де біжить:

        робоча машина    3.12.3 при вимозі 3.12.13  → production_python_exact ХИБНЕ
        продакшен-образ  3.12.13, dev-замка немає   → all_locked_components ХИБНЕ

    Жодне середовище не проходило обидві перевірки. Перевірка, у якої немає стану
    зеленості, не є перевіркою — вона рівно так само мовчить і тоді, коли все
    справді зламано.
    """
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "scripts"))
    import run_exact_environment_gate as gate

    assert set(gate.LOCK_PROFILES) == {"runtime", "development"}
    assert gate.LOCK_PROFILES["runtime"] == (gate.RUNTIME_LOCK,)
    assert gate.DEV_LOCK in gate.LOCK_PROFILES["development"]
    # Класи доказу РІЗНІ: інакше звіт одного середовища читався б як твердження
    # про інше, і саме це відрізняє профіль від прапорця зручності.
    assert len(set(gate.EVIDENCE_CLASSES.values())) == len(gate.EVIDENCE_CLASSES)


def test_a_development_report_cannot_satisfy_the_production_predicate() -> None:
    """Доказ робочої машини не сміє задовольняти твердження про продакшен.

    У профілі `development` перевірки `production_python_exact` НЕМАЄ — не хибна,
    а відсутня, бо dev-машина не продакшен. Без окремої вимоги профілю такий звіт
    задовольнив би предикат рівно тому, що хибної перевірки в ньому немає.
    """
    from korpus.application.production_hard_predicates import _REQUIREMENTS

    requirement = _REQUIREMENTS["exact_python_3_12_13_environment"]
    assert ("profile", "runtime") in requirement.metadata_equals
    assert ("status", "PASS") in requirement.metadata_equals
