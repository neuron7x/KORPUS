from __future__ import annotations

from korpus.application.exact_environment import exact_environment_state


def test_exact_environment_accepts_only_exact_lock_python_and_allowlist() -> None:
    checks, missing, mismatched, extras = exact_environment_state(
        {"a": "1", "b": "2"}, {"a": "1", "b": "2", "pip": "26"},
        python_version="3.12.13", required_python="3.12.13", allowed_unmanaged={"pip"},
        hashes_complete=True,
    )
    assert all(checks.values()), checks
    assert not missing and not mismatched and not extras


def test_unmanaged_distribution_prevents_exact_environment_claim() -> None:
    checks, _, _, extras = exact_environment_state(
        {"a": "1"}, {"a": "1", "rogue-import-hook": "9"},
        python_version="3.12.13", required_python="3.12.13", allowed_unmanaged=set(),
        hashes_complete=True,
    )
    assert checks["no_unmanaged_distributions"] is False
    assert extras == ["rogue-import-hook"]


def test_wrong_python_patch_version_prevents_exact_environment_claim() -> None:
    checks, *_ = exact_environment_state(
        {"a": "1"}, {"a": "1"}, python_version="3.12.12", required_python="3.12.13",
        allowed_unmanaged=set(), hashes_complete=True,
    )
    assert checks["production_python_exact"] is False


def test_missing_or_version_drift_remains_fail_closed() -> None:
    checks, missing, mismatched, _ = exact_environment_state(
        {"a": "1", "b": "2"}, {"a": "9"}, python_version="3.12.13",
        required_python="3.12.13", allowed_unmanaged=set(), hashes_complete=True,
    )
    assert checks["all_locked_components_installed"] is False and missing == ["b"]
    assert checks["all_versions_exact"] is False and mismatched["a"]["installed"] == "9"
