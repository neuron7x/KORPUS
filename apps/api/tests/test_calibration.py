from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from korpus.application.calibration import CalibrationProfile
from korpus.config import Settings


def profile(**overrides):
    values = {
        "profile_id": "calibration-test-v1",
        "dataset_sha256": "a" * 64,
        "accepted_samples": 2000,
        "observed_errors": 10,
        "confidence_delta": 0.05,
        "risk_limit": 0.05,
        "minimum_score": 0.4,
        "minimum_query_coverage": 0.5,
        "minimum_support_score": 0.35,
        "minimum_calibration_samples": 200,
    }
    values.update(overrides)
    return CalibrationProfile(**values)


def test_finite_sample_risk_bound_is_monotone_and_fail_closed():
    low_data = profile(accepted_samples=10, observed_errors=0)
    high_data = profile(accepted_samples=2000, observed_errors=0)
    higher_errors = profile(accepted_samples=2000, observed_errors=40)
    assert low_data.upper_error_bound > high_data.upper_error_bound
    assert higher_errors.upper_error_bound > high_data.upper_error_bound
    assert low_data.deployment_valid is False
    assert high_data.deployment_valid is True


def test_controlled_settings_reject_unvalidated_calibration(tmp_path: Path):
    path = tmp_path / "calibration.json"
    path.write_text(profile(accepted_samples=20, observed_errors=0).model_dump_json())
    with pytest.raises(ValueError, match="finite-sample risk gate"):
        Settings(
            environment="production",
            schema_mode="migrations",
            auth_mode="oidc",
            oidc_jwks_url="https://id.example/jwks",
            jwt_issuer="https://id.example",
            audit_hmac_key="a" * 40,
            answer_policy_mode="calibrated",
            calibration_profile_path=path,
            review_separation_required=True,
        )


def test_controlled_settings_accept_valid_profile(tmp_path: Path):
    path = tmp_path / "calibration.json"
    path.write_text(profile().model_dump_json())
    settings = Settings(
        environment="production",
        schema_mode="migrations",
        auth_mode="oidc",
        oidc_jwks_url="https://id.example/jwks",
        jwt_issuer="https://id.example",
        audit_hmac_key="a" * 40,
        answer_policy_mode="calibrated",
        calibration_profile_path=path,
        review_separation_required=True,
    )
    assert settings.answer_policy_mode == "calibrated"
    assert settings.review_separation_required is True


def test_dataset_digest_is_content_addressed(tmp_path: Path):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_bytes(b'{"id":"x"}\n')
    assert CalibrationProfile.dataset_digest(dataset) == hashlib.sha256(dataset.read_bytes()).hexdigest()
