"""The conditions under which KORPUS may run in a controlled environment, as a list.

These thirty conditions lived inside `Settings.validate_security_and_calibration` as a
run of `if ... raise` statements. Measured on 2026-08-05 that one method carried a
cyclomatic complexity of 103, and `TECHNICAL_DEBT_V5.md` had "decomposition of the
large SQL repository and security configuration validator" open against it.

Complexity was not the reason to move them, and a lower number is not the benefit. The
benefit is that the conditions a deployment must satisfy are now a document that can be
read start to finish — by an engineer, by the security assessor §2.5 asks for, by
whoever signs the authorisation — instead of control flow that has to be traced. The
same list is what `test_controlled_configuration_refusals.py` weakens one entry at a
time, so the register and its refutations sit at the same granularity.

Order is preserved exactly as it was. It is load-bearing: a configuration that violates
several conditions reports the first one, and moving a rule changes which message an
operator sees. The tests that pinned those messages were written before this move, so
any reordering fails them.

Each requirement is a predicate over the settings object and the message raised when it
does not hold. A requirement is stated positively — `holds` is true when the deployment
is acceptable — because a list of negations is read wrong under pressure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

CONTROLLED_ENVIRONMENTS = frozenset({"production", "controlled", "isolated"})


@dataclass(frozen=True)
class ControlledRequirement:
    name: str
    holds: Callable[[Any], bool]
    message: str


def _sslmode(settings: Any) -> str:
    normalized = str(settings.database_url).replace("postgresql+psycopg", "postgresql", 1)
    return parse_qs(urlparse(normalized).query).get("sslmode", [""])[0]


def _browser_settings_present(settings: Any) -> bool:
    return all(
        (
            settings.oidc_authorization_endpoint,
            settings.oidc_token_endpoint,
            settings.oidc_client_id,
            settings.oidc_redirect_uri,
        )
    )


def _file_present(path: Any) -> bool:
    return path is not None and path.is_file()


CONTROLLED_REQUIREMENTS: tuple[ControlledRequirement, ...] = (
    ControlledRequirement(
        "postgresql",
        lambda s: str(s.database_url).startswith("postgresql"),
        "controlled environments require PostgreSQL",
    ),
    ControlledRequirement(
        "verified_tls",
        lambda s: _sslmode(s) == "verify-full",
        "controlled PostgreSQL connections require sslmode=verify-full",
    ),
    ControlledRequirement(
        "oidc",
        lambda s: s.auth_mode == "oidc",
        "OIDC authentication is required in controlled environments",
    ),
    ControlledRequirement(
        "migration_managed_schema",
        lambda s: s.schema_mode == "migrations",
        "controlled environments require migration-managed schema",
    ),
    ControlledRequirement(
        "jwks_url",
        lambda s: bool(s.oidc_jwks_url),
        "OIDC JWKS URL is required",
    ),
    ControlledRequirement(
        "browser_authentication",
        lambda s: bool(s.browser_auth_enabled),
        "controlled environments require browser OIDC/BFF authentication",
    ),
    ControlledRequirement(
        "browser_settings",
        _browser_settings_present,
        "browser OIDC settings are missing: authorization endpoint, token endpoint, "
        "client id, redirect URI",
    ),
    ControlledRequirement(
        "browser_session_key",
        lambda s: bool(s.resolved_browser_session_key)
        and len(s.resolved_browser_session_key) >= 32,
        "controlled browser sessions require a strong session key",
    ),
    ControlledRequirement(
        "secure_cookie",
        lambda s: bool(s.browser_cookie_secure),
        "controlled browser session cookies must be Secure",
    ),
    ControlledRequirement(
        "https_redirect_uri",
        lambda s: str(s.oidc_redirect_uri or "").startswith("https://"),
        "controlled OIDC redirect URI must use HTTPS",
    ),
    ControlledRequirement(
        "entitlement_profile",
        lambda s: _file_present(s.entitlement_profile_path),
        "controlled environments require a server-side entitlement profile",
    ),
    ControlledRequirement(
        "entitlement_profile_digest",
        lambda s: bool(s.entitlement_profile_sha256),
        "controlled environments require an entitlement profile digest",
    ),
    ControlledRequirement(
        "source_signatures",
        lambda s: bool(s.require_source_signatures),
        "controlled environments require detached source signatures",
    ),
    ControlledRequirement(
        "source_trust_profile",
        lambda s: _file_present(s.source_trust_profile_path),
        "controlled environments require a source trust profile",
    ),
    ControlledRequirement(
        "source_trust_profile_digest",
        lambda s: bool(s.source_trust_profile_sha256),
        "controlled environments require a source trust profile digest",
    ),
    ControlledRequirement(
        "reviewer_registry",
        lambda s: _file_present(s.reviewer_registry_path),
        "controlled environments require a reviewer credential registry",
    ),
    ControlledRequirement(
        "reviewer_registry_digest",
        lambda s: bool(s.reviewer_registry_sha256),
        "controlled environments require a reviewer registry digest",
    ),
    ControlledRequirement(
        "corpus_governance_profile",
        lambda s: _file_present(s.corpus_governance_profile_path),
        "controlled environments require a corpus governance profile",
    ),
    ControlledRequirement(
        "corpus_governance_profile_digest",
        lambda s: bool(s.corpus_governance_profile_sha256),
        "controlled environments require a corpus governance profile digest",
    ),
    ControlledRequirement(
        "audit_key",
        lambda s: len(s.resolved_audit_hmac_key) >= 32
        and not s.resolved_audit_hmac_key.startswith("replace-"),
        "production audit key is missing or weak",
    ),
    ControlledRequirement(
        "calibrated_answers",
        lambda s: s.answer_policy_mode == "calibrated" and s.calibration_profile_path is not None,
        "validated calibration profile is required",
    ),
    ControlledRequirement(
        "reviewer_separation",
        lambda s: bool(s.review_separation_required),
        "controlled environments require reviewer separation",
    ),
    ControlledRequirement(
        "remote_audit_anchor",
        lambda s: s.audit_anchor_mode == "http" and bool(s.audit_anchor_url),
        "controlled environments require a remote HTTP audit anchor",
    ),
    ControlledRequirement(
        "audit_anchor_authentication",
        lambda s: bool(s.resolved_audit_anchor_token),
        "controlled environments require audit anchor authentication",
    ),
    ControlledRequirement(
        "metrics",
        lambda s: bool(s.metrics_enabled),
        "controlled environments require operational metrics",
    ),
    ControlledRequirement(
        "metrics_authentication",
        lambda s: bool(s.resolved_metrics_token),
        "controlled environments require an authenticated metrics endpoint",
    ),
    ControlledRequirement(
        "explicit_https_cors",
        lambda s: all(
            origin != "*" and origin.startswith("https://") for origin in s.cors_origin_list
        ),
        "controlled CORS origins must be explicit HTTPS origins",
    ),
    ControlledRequirement(
        "explicit_trusted_hosts",
        lambda s: bool(s.trusted_host_list) and "*" not in s.trusted_host_list,
        "controlled environments require explicit trusted hosts",
    ),
    ControlledRequirement(
        "https_s3_endpoint",
        lambda s: not s.s3_endpoint_url or str(s.s3_endpoint_url).startswith("https://"),
        "controlled S3 endpoints must use HTTPS",
    ),
    ControlledRequirement(
        "object_governance_retention",
        lambda s: s.s3_governance_retention_days >= 1,
        "controlled object storage requires governance retention",
    ),
    ControlledRequirement(
        "durable_ingestion",
        lambda s: s.ingestion_mode == "durable_async",
        "controlled environments require durable asynchronous ingestion",
    ),
    ControlledRequirement(
        "malware_scanning",
        lambda s: s.malware_scan_mode == "clamd",
        "controlled environments require fail-closed malware scanning",
    ),
    ControlledRequirement(
        "parser_isolation",
        lambda s: bool(s.parser_sandbox_enabled),
        "controlled environments require parser process isolation",
    ),
    ControlledRequirement(
        "https_otlp_endpoint",
        lambda s: not s.otlp_endpoint or str(s.otlp_endpoint).startswith("https://"),
        "controlled OTLP endpoints must use HTTPS",
    ),
)


def first_unmet(settings: Any) -> ControlledRequirement | None:
    """The first requirement this deployment does not satisfy, in declared order."""
    for requirement in CONTROLLED_REQUIREMENTS:
        if not requirement.holds(settings):
            return requirement
    return None
