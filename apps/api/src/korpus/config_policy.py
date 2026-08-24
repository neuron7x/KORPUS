from __future__ import annotations

from typing import Any

from korpus.application.calibration import CalibrationProfile
from korpus.billing_config_policy import validate_billing_settings
from korpus.controlled_requirements import first_unmet
from korpus.model_settings import resolved_model_api_key, validate_model_provider
from korpus.offline_pack_config_policy import validate_offline_pack_settings
from korpus.pec_config_policy import validate_pec_settings
from korpus.runtime_config_policy import validate_storage_integrations
from korpus.security.browser_cookie_policy import validate_browser_cookie_policy
from korpus.security.external_destination import parse_external_https_url
from korpus.security.url_policy import is_browser_redirect_url, is_https_url


def validate_runtime_settings(settings: Any) -> None:
    """Validate cross-field runtime policy in contractual failure order."""
    controlled = settings.environment in {"production", "controlled", "isolated"}
    _validate_auth(settings, controlled=controlled)
    _validate_controlled_requirements(settings, controlled=controlled)
    _validate_browser_oidc(settings, controlled=controlled)
    _validate_model_integrations(settings)
    _validate_semantic_retrieval(settings, controlled=controlled)
    _validate_runtime_integrations(settings, controlled=controlled)
    validate_billing_settings(settings)
    validate_offline_pack_settings(settings)
    _load_security_profiles(settings)
    _validate_calibration(settings)
    validate_pec_settings(settings, controlled=controlled)


def _validate_auth(settings: Any, *, controlled: bool) -> None:
    # Only the HTTP API accepts end-user credentials. Background workers are authenticated
    # to Google Cloud by workload identity and replay the already-authorized actor snapshot
    # stored with each durable ingestion job. Requiring browser/OIDC secrets in a worker
    # expands the secret blast radius without adding an authentication boundary.
    if settings.runtime_role != "api":
        if settings.auth_mode == "dev":
            raise ValueError("background runtime roles cannot use dev authentication")
        return
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


def _validate_browser_oidc(settings: Any, *, controlled: bool) -> None:
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
    validate_browser_cookie_policy(settings, controlled=controlled)
    authorization_endpoint = settings.oidc_authorization_endpoint or ""
    token_endpoint = settings.oidc_token_endpoint or ""
    redirect_uri = settings.oidc_redirect_uri or ""
    for endpoint, label in ((authorization_endpoint, "authorization"), (token_endpoint, "token")):
        try:
            parse_external_https_url(endpoint, name=f"OIDC {label} endpoint")
        except ValueError as exc:
            raise ValueError("OIDC browser endpoints must use HTTPS external destinations") from exc
    if not is_browser_redirect_url(redirect_uri):
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
        if controlled and not is_https_url(settings.embedding_endpoint):
            raise ValueError("controlled embedding endpoints must use HTTPS")
        if controlled and not settings.resolved_embedding_token:
            raise ValueError("controlled embedding integration requires authentication")
    elif settings.semantic_weight != 0:
        raise ValueError("semantic weight must be zero when semantic retrieval is disabled")


def _validate_runtime_integrations(settings: Any, *, controlled: bool) -> None:
    validate_storage_integrations(settings, controlled=controlled)
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
        name for name, path in required_artifacts.items() if path is None or not path.is_file()
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
