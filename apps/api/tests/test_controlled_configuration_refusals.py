"""Every refusal a controlled deployment depends on, shown refusing.

`Settings.validate_security_and_calibration` states around thirty conditions that a
production, controlled or isolated deployment must satisfy: PostgreSQL over verified
TLS, OIDC, migration-managed schema, a signed entitlement profile, detached source
signatures, a reviewer registry, a remote audit anchor with authentication,
fail-closed malware scanning, parser isolation, explicit HTTPS origins and hosts.

Two of them had a test. The rest were prose that happened to be written in Python:
nothing had ever observed them refuse anything, and a validator that has never
rejected a configuration is indistinguishable from one that returns None. That is the
§2.8 argument applied where it matters most — these are the conditions under which the
system is allowed to run at all.

The shape is one base configuration that must be accepted, and one deliberate
weakening per requirement that must be rejected with the message naming it. The dual
matters as much as the cases: if the base were invalid for some unrelated reason,
every "rejected" below would be vacuous.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from korpus.config import Settings

from apps.api.tests.security_fixtures import controlled_security_kwargs, write_calibration_bundle

CONTROLLED_DATABASE = "postgresql+psycopg://u:p@db/korpus?sslmode=verify-full"


def _base(tmp_path: Path) -> dict[str, Any]:
    return dict(
        environment="production",
        database_url=CONTROLLED_DATABASE,
        schema_mode="migrations",
        object_store_mode="s3",
        s3_bucket="korpus",
        s3_governance_retention_days=30,
        auth_mode="oidc",
        oidc_jwks_url="https://id.example/jwks",
        jwt_issuer="https://id.example",
        audit_hmac_key="a" * 40,
        audit_anchor_mode="http",
        audit_anchor_url="https://anchor.example/v1/head",
        audit_anchor_token="anchor-token",
        answer_policy_mode="calibrated",
        review_separation_required=True,
        metrics_enabled=True,
        metrics_token="metrics-token",
        cors_origins="https://korpus.example",
        trusted_hosts="korpus.example",
        **write_calibration_bundle(tmp_path),
        **controlled_security_kwargs(tmp_path),
    )


def test_the_base_controlled_configuration_is_accepted(tmp_path: Path) -> None:
    """The dual. Without it every rejection below could be for the wrong reason."""
    settings = Settings(**_base(tmp_path))
    assert settings.environment == "production"
    assert settings.auth_mode == "oidc"


#: requirement -> (field overrides that violate exactly it, fragment of its message)
WEAKENINGS: dict[str, tuple[dict[str, Any], str]] = {
    "sqlite instead of postgresql": (
        {"database_url": "sqlite:///./var/korpus.db"},
        "require PostgreSQL",
    ),
    "postgresql without verified TLS": (
        {"database_url": "postgresql+psycopg://u:p@db/korpus"},
        "sslmode=verify-full",
    ),
    "tls mode that only encrypts": (
        {"database_url": "postgresql+psycopg://u:p@db/korpus?sslmode=require"},
        "sslmode=verify-full",
    ),
    "authentication disabled": ({"auth_mode": "disabled"}, "cannot disable authentication"),
    "dev authentication": ({"auth_mode": "dev"}, "dev authentication is forbidden"),
    "bearer jwt instead of oidc": ({"auth_mode": "jwt"}, "OIDC authentication is required"),
    "schema created by the application": (
        {"schema_mode": "auto"},
        "migration-managed schema",
    ),
    "no jwks url": ({"oidc_jwks_url": None}, "JWKS URL is required"),
    "browser authentication off": (
        {"browser_auth_enabled": False},
        "browser OIDC/BFF authentication",
    ),
    "no browser redirect uri": ({"oidc_redirect_uri": None}, "browser OIDC settings are missing"),
    "session cookie without Secure": (
        {"browser_cookie_secure": False},
        "cookies must be Secure",
    ),
    "weak browser session key": (
        {"browser_session_key": "short"},
        "strong session key",
    ),
    "no entitlement profile": (
        {"entitlement_profile_path": None},
        "server-side entitlement profile",
    ),
    "entitlement profile without a digest": (
        {"entitlement_profile_sha256": None},
        "entitlement profile digest",
    ),
    "source signatures not required": (
        {"require_source_signatures": False},
        "detached source signatures",
    ),
    "no source trust profile": (
        {"source_trust_profile_path": None},
        "source trust profile",
    ),
    "source trust profile without a digest": (
        {"source_trust_profile_sha256": None},
        "source trust profile digest",
    ),
    "no reviewer registry": (
        {"reviewer_registry_path": None},
        "reviewer credential registry",
    ),
    "reviewer registry without a digest": (
        {"reviewer_registry_sha256": None},
        "reviewer registry digest",
    ),
    "no corpus governance profile": (
        {"corpus_governance_profile_path": None},
        "corpus governance profile",
    ),
    "governance profile without a digest": (
        {"corpus_governance_profile_sha256": None},
        "corpus governance profile digest",
    ),
    "placeholder audit key": (
        {"audit_hmac_key": "replace-me-before-production-000000000000"},
        "audit key is missing or weak",
    ),
    "short audit key": ({"audit_hmac_key": "a" * 8}, "audit key is missing or weak"),
    "uncalibrated answer policy": (
        {"answer_policy_mode": "development"},
        "validated calibration profile",
    ),
    "reviewer separation waived": (
        {"review_separation_required": False},
        "reviewer separation",
    ),
    "audit anchored to a local file": (
        {"audit_anchor_mode": "file"},
        "remote HTTPS audit anchor",
    ),
    "audit anchor without authentication": (
        {"audit_anchor_token": None},
        "audit anchor authentication",
    ),
    "plaintext audit anchor": (
        {"audit_anchor_url": "http://anchor.example/v1/head"},
        "remote HTTPS audit anchor",
    ),
    "loopback audit anchor": (
        {"audit_anchor_url": "https://127.0.0.1/v1/head"},
        "remote HTTPS audit anchor",
    ),
    "session cookie without host prefix": (
        {"browser_session_cookie": "korpus_session"},
        "__Host- prefix",
    ),
    "csrf cookie without host prefix": (
        {"browser_csrf_cookie": "korpus_csrf"},
        "__Host- prefix",
    ),
    "flow cookie without secure prefix": (
        {"browser_flow_cookie": "korpus_flow"},
        "__Secure- prefix",
    ),
    "duplicate browser cookie names": (
        {"browser_flow_cookie": "__Host-korpus_session"},
        "cookie names must be distinct",
    ),
    "placeholder browser session key": (
        {"browser_session_key": "replace-browser-session-key-0000000000000000"},
        "must not be a placeholder",
    ),
    "metrics disabled": ({"metrics_enabled": False}, "operational metrics"),
    "metrics endpoint unauthenticated": (
        {"metrics_token": None},
        "authenticated metrics endpoint",
    ),
    "wildcard cors": ({"cors_origins": "*"}, "explicit HTTPS origins"),
    "plaintext cors origin": (
        {"cors_origins": "http://korpus.example"},
        "explicit HTTPS origins",
    ),
    "wildcard trusted host": ({"trusted_hosts": "*"}, "explicit trusted hosts"),
    "plaintext s3 endpoint": (
        {"s3_endpoint_url": "http://minio.internal:9000"},
        "S3 endpoints must use HTTPS",
    ),
    "no object governance retention": (
        {"s3_governance_retention_days": 0},
        "governance retention",
    ),
    "synchronous ingestion": ({"ingestion_mode": "synchronous"}, "durable asynchronous ingestion"),
    "malware scanning disabled": (
        {"malware_scan_mode": "disabled"},
        "fail-closed malware scanning",
    ),
    "parser sandbox disabled": (
        {"parser_sandbox_enabled": False},
        "parser process isolation",
    ),
    "plaintext otlp endpoint": (
        {"otlp_endpoint": "http://collector.internal:4317"},
        "OTLP endpoints must use HTTPS",
    ),
}


@pytest.mark.parametrize("requirement", sorted(WEAKENINGS))
def test_a_controlled_deployment_refuses_each_weakening(requirement: str, tmp_path: Path) -> None:
    overrides, message = WEAKENINGS[requirement]
    role = "worker" if requirement in {"malware scanning disabled", "parser sandbox disabled"} else "api"
    settings = _base(tmp_path) | {"runtime_role": role} | overrides

    with pytest.raises(ValueError, match=message):
        Settings(**settings)


@pytest.mark.parametrize("environment", ["production", "controlled", "isolated"])
def test_every_controlled_environment_name_carries_the_same_refusals(
    environment: str, tmp_path: Path
) -> None:
    """"controlled" and "isolated" are not weaker spellings of "production".

    A deployment that names itself differently must not thereby acquire permission to
    run on SQLite without authentication.
    """
    settings = _base(tmp_path) | {
        "environment": environment,
        "database_url": "sqlite:///./var/korpus.db",
    }

    with pytest.raises(ValueError, match="require PostgreSQL"):
        Settings(**settings)



def test_gcp_production_configuration_is_accepted(tmp_path: Path) -> None:
    """The managed-GCP production path satisfies the same controlled predicates."""
    settings = Settings(
        **(
            _base(tmp_path)
            | {
                "database_url": (
                    "postgresql+psycopg://korpus_app:p@/korpus"
                    "?host=/cloudsql/project:europe-west1:korpus-prod"
                ),
                "database_transport": "cloud_sql_socket",
                "object_store_mode": "gcs",
                "gcs_bucket": "korpus-prod-objects",
                "gcs_quarantine_bucket": "korpus-prod-quarantine",
                "gcs_retention_seconds": 30 * 24 * 3600,
                "audit_anchor_mode": "gcs",
                "gcs_audit_bucket": "korpus-prod-audit",
                "audit_anchor_url": None,
                "audit_anchor_token": None,
                "s3_bucket": None,
                "s3_governance_retention_days": 0,
            }
        )
    )
    assert settings.database_transport == "cloud_sql_socket"
    assert settings.object_store_mode == "gcs"
    assert settings.audit_anchor_mode == "gcs"


def test_cloud_sql_socket_transport_refuses_a_network_hostname(tmp_path: Path) -> None:
    settings = _base(tmp_path) | {
        "database_url": (
            "postgresql+psycopg://korpus_app:p@db.example/korpus"
            "?host=/cloudsql/project:europe-west1:korpus-prod"
        ),
        "database_transport": "cloud_sql_socket",
    }
    with pytest.raises(ValueError, match="Cloud SQL Unix socket transport"):
        Settings(**settings)


def test_direct_tls_transport_still_requires_peer_verification(tmp_path: Path) -> None:
    settings = _base(tmp_path) | {
        "database_url": "postgresql+psycopg://u:p@db/korpus?sslmode=require",
        "database_transport": "direct_tls",
    }
    with pytest.raises(ValueError, match="sslmode=verify-full"):
        Settings(**settings)

def test_a_local_environment_is_not_held_to_the_controlled_requirements(tmp_path: Path) -> None:
    """The refusals have to be conditional, or they would say nothing about control.

    A validator that rejects every configuration is as uninformative as one that
    accepts every configuration.
    """
    settings = Settings(
        environment="local",
        database_url="sqlite:///./var/korpus.db",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
    )
    assert settings.environment == "local"


def test_production_worker_does_not_receive_browser_or_oidc_secrets(tmp_path: Path) -> None:
    """A background ingestion principal is not an HTTP authentication principal.

    The worker must still satisfy DB, durable-storage, provenance, audit, malware and
    parser-isolation predicates, but giving it browser/OIDC secrets only widens the
    credential blast radius. This test makes least privilege executable.
    """
    security = controlled_security_kwargs(tmp_path)
    for key in (
        "entitlement_profile_path",
        "entitlement_profile_sha256",
        "browser_auth_enabled",
        "browser_session_key",
        "browser_cookie_secure",
        "oidc_authorization_endpoint",
        "oidc_token_endpoint",
        "oidc_client_id",
        "oidc_redirect_uri",
    ):
        security.pop(key, None)
    settings = Settings(
        environment="production",
        runtime_role="worker",
        database_url=(
            "postgresql+psycopg://korpus_app:p@/korpus"
            "?host=/cloudsql/project:europe-central2:korpus-prod"
        ),
        database_transport="cloud_sql_socket",
        schema_mode="migrations",
        object_store_mode="gcs",
        gcs_bucket="korpus-prod-objects",
        gcs_quarantine_bucket="korpus-prod-quarantine",
        gcs_retention_seconds=30 * 24 * 3600,
        auth_mode="disabled",
        audit_hmac_key="a" * 40,
        audit_anchor_mode="gcs",
        gcs_audit_bucket="korpus-prod-audit",
        answer_policy_mode="development",
        review_separation_required=True,
        metrics_enabled=False,
        cors_origins="*",
        trusted_hosts="*",
        **security,
    )
    assert settings.runtime_role == "worker"
    assert settings.auth_mode == "disabled"
    assert settings.browser_auth_enabled is False


def test_production_api_still_refuses_browser_authentication_removal(tmp_path: Path) -> None:
    settings = _base(tmp_path) | {"runtime_role": "api", "browser_auth_enabled": False}
    with pytest.raises(ValueError, match="browser OIDC/BFF authentication"):
        Settings(**settings)


def test_background_runtime_refuses_dev_auth_even_outside_http_api(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="background runtime roles cannot use dev authentication"):
        Settings(
            environment="local",
            runtime_role="worker",
            auth_mode="dev",
            dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        )
