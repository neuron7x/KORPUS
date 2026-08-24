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

from typing import Any
from korpus.security.url_policy import is_https_origin, is_https_url
from korpus.security.destination_predicates import is_external_https_url
from korpus.controlled_requirement_core import (
    API_ONLY, WORKER_ONLY, ControlledRequirement, browser_settings_present,
    file_present, verified_database_transport,
)

CONTROLLED_ENVIRONMENTS = frozenset({"production", "controlled", "isolated"})

CONTROLLED_REQUIREMENTS: tuple[ControlledRequirement, ...] = (
    ControlledRequirement(
        "postgresql",
        lambda s: str(s.database_url).startswith("postgresql"),
        "controlled environments require PostgreSQL",
    ),
    ControlledRequirement(
        "verified_database_transport",
        verified_database_transport,
        "controlled PostgreSQL connections require sslmode=verify-full or an explicit Cloud SQL Unix socket transport",
    ),
    ControlledRequirement(
        "oidc",
        lambda s: s.auth_mode == "oidc",
        "OIDC authentication is required in controlled environments",
        roles=API_ONLY,
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
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "browser_authentication",
        lambda s: bool(s.browser_auth_enabled),
        "controlled environments require browser OIDC/BFF authentication",
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "browser_settings",
        browser_settings_present,
        "browser OIDC settings are missing: authorization endpoint, token endpoint, "
        "client id, redirect URI",
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "browser_session_key",
        lambda s: bool(s.resolved_browser_session_key)
        and len(s.resolved_browser_session_key) >= 32,
        "controlled browser sessions require a strong session key",
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "secure_cookie",
        lambda s: bool(s.browser_cookie_secure),
        "controlled browser session cookies must be Secure",
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "https_redirect_uri",
        lambda s: is_https_url(s.oidc_redirect_uri or ""),
        "controlled OIDC redirect URI must use HTTPS",
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "entitlement_profile",
        lambda s: file_present(s.entitlement_profile_path),
        "controlled environments require a server-side entitlement profile",
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "entitlement_profile_digest",
        lambda s: bool(s.entitlement_profile_sha256),
        "controlled environments require an entitlement profile digest",
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "source_signatures",
        lambda s: bool(s.require_source_signatures),
        "controlled environments require detached source signatures",
    ),
    ControlledRequirement(
        "source_trust_profile",
        lambda s: file_present(s.source_trust_profile_path),
        "controlled environments require a source trust profile",
    ),
    ControlledRequirement(
        "source_trust_profile_digest",
        lambda s: bool(s.source_trust_profile_sha256),
        "controlled environments require a source trust profile digest",
    ),
    ControlledRequirement(
        "reviewer_registry",
        lambda s: file_present(s.reviewer_registry_path),
        "controlled environments require a reviewer credential registry",
    ),
    ControlledRequirement(
        "reviewer_registry_digest",
        lambda s: bool(s.reviewer_registry_sha256),
        "controlled environments require a reviewer registry digest",
    ),
    ControlledRequirement(
        "corpus_governance_profile",
        lambda s: file_present(s.corpus_governance_profile_path),
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
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "reviewer_separation",
        lambda s: bool(s.review_separation_required),
        "controlled environments require reviewer separation",
    ),
    ControlledRequirement(
        "remote_audit_anchor",
        lambda s: (s.audit_anchor_mode == "http" and is_external_https_url(s.audit_anchor_url))
        or (s.audit_anchor_mode == "gcs" and bool(s.gcs_audit_bucket)),
        "controlled environments require a remote HTTPS audit anchor or GCS audit anchor",
    ),
    ControlledRequirement(
        "audit_anchor_authentication",
        lambda s: (s.audit_anchor_mode == "http" and bool(s.resolved_audit_anchor_token))
        or s.audit_anchor_mode == "gcs",
        "controlled environments require audit anchor authentication",
    ),
    ControlledRequirement(
        "metrics",
        lambda s: bool(s.metrics_enabled),
        "controlled environments require operational metrics",
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "metrics_authentication",
        lambda s: bool(s.resolved_metrics_token),
        "controlled environments require an authenticated metrics endpoint",
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "explicit_https_cors",
        lambda s: all(origin != "*" and is_https_origin(origin) for origin in s.cors_origin_list),
        "controlled CORS origins must be explicit HTTPS origins",
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "explicit_trusted_hosts",
        lambda s: bool(s.trusted_host_list) and "*" not in s.trusted_host_list,
        "controlled environments require explicit trusted hosts",
        roles=API_ONLY,
    ),
    ControlledRequirement(
        "https_s3_endpoint",
        lambda s: not s.s3_endpoint_url or is_https_url(s.s3_endpoint_url),
        "controlled S3 endpoints must use HTTPS",
    ),
    ControlledRequirement(
        "object_governance_retention",
        lambda s: (s.object_store_mode == "s3" and s.s3_governance_retention_days >= 1)
        or (s.object_store_mode == "gcs" and s.gcs_retention_seconds >= 1),
        "controlled object storage requires governance retention",
    ),
    ControlledRequirement(
        "gcs_quarantine_separation",
        lambda s: s.object_store_mode != "gcs"
        or (bool(s.gcs_quarantine_bucket) and s.gcs_quarantine_bucket != s.gcs_bucket),
        "controlled GCS deployments require a separate quarantine bucket",
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
        roles=WORKER_ONLY,
    ),
    ControlledRequirement(
        "parser_isolation",
        lambda s: bool(s.parser_sandbox_enabled),
        "controlled environments require parser process isolation",
        roles=WORKER_ONLY,
    ),
    ControlledRequirement(
        "https_otlp_endpoint",
        lambda s: not s.otlp_endpoint or is_https_url(s.otlp_endpoint),
        "controlled OTLP endpoints must use HTTPS",
    ),
)


def first_unmet(settings: Any) -> ControlledRequirement | None:
    """The first requirement this deployment does not satisfy, in declared order."""
    for requirement in CONTROLLED_REQUIREMENTS:
        if requirement.violated(settings):
            return requirement
    return None
