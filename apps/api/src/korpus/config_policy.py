from __future__ import annotations

from typing import Any

from sqlalchemy.engine import make_url

from korpus.application.calibration import CalibrationProfile
from korpus.billing_config_policy import validate_billing_settings
from korpus.controlled_requirements import first_unmet
from korpus.model_settings import resolved_model_api_key, validate_model_provider


def validate_runtime_settings(settings: Any) -> None:
    """Validate cross-field runtime policy in contractual failure order."""
    controlled = settings.environment in {"production", "controlled", "isolated"}
    _validate_auth(settings, controlled=controlled)
    _validate_controlled_requirements(settings, controlled=controlled)
    _validate_browser_oidc(settings)
    _validate_model_integrations(settings)
    _validate_semantic_retrieval(settings, controlled=controlled)
    _validate_runtime_integrations(settings, controlled=controlled)
    validate_billing_settings(settings)
    _load_security_profiles(settings)
    _validate_calibration(settings)


def _validate_auth(settings: Any, *, controlled: bool) -> None:
    if settings.auth_mode == "dev":
        if settings.environment not in {"local", "test", "development"}:
            raise ValueError(
                "OIDC authentication is required in controlled environments; "
                "dev authentication is forbidden"
            )
        if settings.dev_mode_acknowledgement != "I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE":
            raise ValueError("dev authentication requires explicit acknowledgement")
        if settings.bind_host not in {"127.0.0.1", "::1", "localhost", "testserver"}:
            raise ValueError("dev authentication requires loopback-only binding")
    if settings.auth_mode == "disabled" and controlled:
        raise ValueError("controlled environments cannot disable authentication")


def _validate_controlled_requirements(settings: Any, *, controlled: bool) -> None:
    if not controlled:
        return
    unmet = first_unmet(settings)
    if unmet is not None:
        raise ValueError(unmet.message)


def _validate_browser_oidc(settings: Any) -> None:
    if not settings.browser_auth_enabled:
        return
    if settings.auth_mode != "oidc":
        raise ValueError("browser authentication requires OIDC mode")
    required = [
        settings.oidc_authorization_endpoint,
        settings.oidc_token_endpoint,
        settings.oidc_client_id,
        settings.oidc_redirect_uri,
    ]
    if any(not value for value in required):
        raise ValueError("browser OIDC endpoints, client id, and redirect URI are required")
    if not settings.resolved_browser_session_key or len(settings.resolved_browser_session_key) < 32:
        raise ValueError("browser session key must contain at least 32 characters")
    authorization_endpoint = settings.oidc_authorization_endpoint or ""
    token_endpoint = settings.oidc_token_endpoint or ""
    redirect_uri = settings.oidc_redirect_uri or ""
    if not authorization_endpoint.startswith("https://") or not token_endpoint.startswith(
        "https://"
    ):
        raise ValueError("OIDC browser endpoints must use HTTPS")
    loopback_prefixes = (
        "https://",
        "http://127.0.0.1",
        "http://localhost",
        "http://testserver",
    )
    if not redirect_uri.startswith(loopback_prefixes):
        raise ValueError("OIDC redirect URI must be HTTPS or an explicit loopback test URI")


def _validate_model_integrations(settings: Any) -> None:
    validate_model_provider(settings)
    if settings.answer_composer_enabled and not resolved_model_api_key(settings):
        raise ValueError("answer composer is enabled without an API key")
    if settings.answer_composer_enabled and settings.environment in {"controlled", "isolated"}:
        raise ValueError(
            "the answer composer sends retrieved passages to a third party and is "
            f"refused in a {settings.environment} environment"
        )
    if settings.query_planner_enabled and not resolved_model_api_key(settings):
        raise ValueError("query planner is enabled without an API key")
    if settings.query_planner_enabled and settings.environment in {"controlled", "isolated"}:
        raise ValueError(
            "query planner sends every question to a third party and is refused in "
            f"a {settings.environment} environment"
        )


def _validate_semantic_retrieval(settings: Any, *, controlled: bool) -> None:
    if settings.semantic_retrieval_enabled:
        if not settings.database_url.startswith("postgresql"):
            raise ValueError("semantic retrieval requires PostgreSQL/pgvector")
        if not settings.embedding_endpoint or not settings.embedding_model_id:
            raise ValueError("semantic retrieval requires embedding endpoint and model id")
        if settings.semantic_weight <= 0 and settings.answer_policy_mode == "development":
            raise ValueError("semantic retrieval requires a positive semantic weight")
        if controlled and not settings.embedding_endpoint.startswith("https://"):
            raise ValueError("controlled embedding endpoints must use HTTPS")
        if controlled and not settings.resolved_embedding_token:
            raise ValueError("controlled embedding integration requires authentication")
    elif settings.semantic_weight != 0:
        raise ValueError("semantic weight must be zero when semantic retrieval is disabled")


def _validate_review_identity(settings: Any, *, controlled: bool) -> None:
    postgres = settings.database_url.startswith("postgresql")
    review_url = settings.review_database_url
    if controlled and postgres and not review_url:
        raise ValueError("controlled PostgreSQL requires a separate review database identity")
    if not review_url:
        return
    if not postgres:
        raise ValueError("review database identity is valid only with PostgreSQL")
    primary, review = make_url(settings.database_url), make_url(review_url)
    primary_target = (primary.get_backend_name(), primary.host, primary.port, primary.database)
    review_target = (review.get_backend_name(), review.host, review.port, review.database)
    if primary_target != review_target:
        raise ValueError("review database identity must target the primary PostgreSQL database")
    if not review.username or review.username == primary.username:
        raise ValueError("review database identity must use a distinct PostgreSQL login")


def _validate_runtime_integrations(settings: Any, *, controlled: bool) -> None:
    if settings.audit_anchor_mode == "http" and not settings.audit_anchor_url:
        raise ValueError("audit_anchor_url is required for HTTP audit anchoring")
    if settings.object_store_mode == "s3" and not settings.s3_bucket:
        raise ValueError("s3_bucket is required for S3 object storage")
    if controlled and settings.object_store_mode == "local":
        raise ValueError("controlled environments require durable S3-compatible object storage")
    _validate_review_identity(settings, controlled=controlled)
    if settings.auth_mode == "jwt" and (
        len(settings.resolved_jwt_secret) < 32
        or settings.resolved_jwt_secret.startswith("replace-")
    ):
        raise ValueError("JWT secret is missing or weak")
    if settings.chunk_overlap_chars >= settings.max_chunk_chars:
        raise ValueError("chunk overlap must be smaller than chunk size")


def _load_security_profiles(settings: Any) -> None:
    if settings.entitlement_profile_path is not None:
        from korpus.security.entitlements import EntitlementProfile

        EntitlementProfile.load(
            settings.entitlement_profile_path,
            settings.entitlement_profile_sha256,
        )
    if settings.source_trust_profile_path is not None:
        from korpus.security.source_authenticity import SourceTrustProfile

        SourceTrustProfile.load(
            settings.source_trust_profile_path,
            settings.source_trust_profile_sha256,
        )
    if settings.require_source_signatures and settings.source_trust_profile_path is None:
        raise ValueError("source signatures require a source trust profile")
    if settings.reviewer_registry_path is not None:
        from korpus.security.reviewers import ReviewerRegistry

        ReviewerRegistry.load(
            settings.reviewer_registry_path,
            settings.reviewer_registry_sha256,
        )
    if settings.corpus_governance_profile_path is not None:
        from korpus.security.corpus_governance import CorpusGovernanceProfile

        CorpusGovernanceProfile.load(
            settings.corpus_governance_profile_path,
            settings.corpus_governance_profile_sha256,
        )


def _validate_calibration(settings: Any) -> None:
    if settings.answer_policy_mode != "calibrated":
        return
    profile_path = settings.calibration_profile_path
    dataset_path = settings.calibration_dataset_path
    manifest_path = settings.calibration_system_manifest_path
    protocol_path = settings.calibration_evaluation_protocol_path
    required_artifacts = {
        "profile": profile_path,
        "dataset": dataset_path,
        "system manifest": manifest_path,
        "evaluation protocol": protocol_path,
    }
    missing = [
        name
        for name, path in required_artifacts.items()
        if path is None or not path.is_file()
    ]
    if (
        missing
        or profile_path is None
        or dataset_path is None
        or manifest_path is None
        or protocol_path is None
    ):
        raise ValueError(f"calibration artifacts are missing: {', '.join(missing)}")
    if not settings.calibration_profile_sha256:
        raise ValueError("calibration profile digest is required")
    profile = CalibrationProfile.load(
        profile_path,
        expected_sha256=settings.calibration_profile_sha256,
    )
    profile.validate_artifact_bindings(
        dataset=dataset_path,
        system_manifest=manifest_path,
        evaluation_protocol=protocol_path,
    )
    if not profile.deployment_valid:
        raise ValueError("calibration profile does not satisfy finite-sample risk gate")
    if profile.weight_semantic > 0 and not settings.semantic_retrieval_enabled:
        raise ValueError("calibration profile requires semantic retrieval but it is disabled")
    if settings.semantic_retrieval_enabled and profile.weight_semantic <= 0:
        raise ValueError(
            "semantic retrieval is enabled but calibration assigns zero semantic weight"
        )
