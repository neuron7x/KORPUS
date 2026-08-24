from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from korpus.application.calibration import CalibrationProfile
from korpus.config import Settings

from apps.api.tests.security_fixtures import controlled_security_kwargs, write_calibration_bundle


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
        "ranking_evaluated_queries": 500,
        "ndcg_at_10": 0.82,
        "mrr_at_10": 0.86,
        "recall_at_20": 0.94,
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
    calibration = write_calibration_bundle(tmp_path, accepted_samples=20, observed_errors=0)
    with pytest.raises(ValueError, match="finite-sample risk gate"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://user:pass@db/korpus?sslmode=verify-full",
            schema_mode="migrations",
            object_store_mode="s3",
            s3_bucket="korpus-test",
            s3_governance_retention_days=30,
            auth_mode="oidc",
            oidc_jwks_url="https://id.example/jwks",
            jwt_issuer="https://id.example",
            audit_hmac_key="a" * 40,
            audit_anchor_mode="http",
            audit_anchor_url="https://anchor.example/v1/head",
            audit_anchor_token="anchor-test-token",
            answer_policy_mode="calibrated",
            review_separation_required=True,
            metrics_token="metrics-test-token",
            cors_origins="https://korpus.example",
            **calibration,
            **controlled_security_kwargs(tmp_path),
        )


def test_controlled_settings_accept_valid_profile(tmp_path: Path):
    calibration = write_calibration_bundle(tmp_path)
    settings = Settings(
        environment="production",
        database_url="postgresql+psycopg://user:pass@db/korpus?sslmode=verify-full",
        schema_mode="migrations",
        object_store_mode="s3",
        s3_bucket="korpus-test",
        s3_governance_retention_days=30,
        auth_mode="oidc",
        oidc_jwks_url="https://id.example/jwks",
        jwt_issuer="https://id.example",
        audit_hmac_key="a" * 40,
        audit_anchor_mode="http",
        audit_anchor_url="https://anchor.example/v1/head",
        audit_anchor_token="anchor-test-token",
        answer_policy_mode="calibrated",
        review_separation_required=True,
        metrics_token="metrics-test-token",
        cors_origins="https://korpus.example",
        **calibration,
        **controlled_security_kwargs(tmp_path),
    )
    assert settings.answer_policy_mode == "calibrated"
    assert settings.review_separation_required is True


def test_calibration_profile_and_bound_artifacts_reject_tampering(tmp_path: Path):
    calibration = write_calibration_bundle(tmp_path)
    settings = Settings(answer_policy_mode="calibrated", **calibration)
    assert settings.answer_policy_mode == "calibrated"

    dataset = calibration["calibration_dataset_path"]
    assert isinstance(dataset, Path)
    dataset.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="dataset digest mismatch"):
        Settings(answer_policy_mode="calibrated", **calibration)

    calibration = write_calibration_bundle(tmp_path / "second")
    profile_path = calibration["calibration_profile_path"]
    assert isinstance(profile_path, Path)
    profile_path.write_text(profile_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="profile digest mismatch"):
        Settings(answer_policy_mode="calibrated", **calibration)


def test_dataset_digest_is_content_addressed(tmp_path: Path):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_bytes(b'{"id":"x"}\n')
    assert (
        CalibrationProfile.dataset_digest(dataset)
        == hashlib.sha256(dataset.read_bytes()).hexdigest()
    )
