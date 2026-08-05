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
        "remote HTTP audit anchor",
    ),
    "audit anchor without authentication": (
        {"audit_anchor_token": None},
        "audit anchor authentication",
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
    settings = _base(tmp_path) | overrides

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
