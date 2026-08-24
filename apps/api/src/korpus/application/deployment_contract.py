"""Shared, behavior-free deployment contract constants.

Both the renderer and the requirement registry depend on this module. Keeping these
constants here prevents the renderer and the policy registry from importing each other.
"""

from __future__ import annotations

SUPPORTED_KUSTOMIZATION_FIELDS = frozenset(
    {"apiVersion", "kind", "namespace", "resources", "patches"}
)
REQUIRED_KINDS = frozenset(
    {
        "Namespace",
        "Deployment",
        "Service",
        "Job",
        "NetworkPolicy",
        "PodDisruptionBudget",
        "HorizontalPodAutoscaler",
        "ServiceAccount",
        "ConfigMap",
    }
)
REQUIRED_WORKLOADS = frozenset({"korpus-api", "korpus-worker", "korpus-web"})
REQUIRED_PRODUCTION_CONFIG = {
    "KORPUS_ENVIRONMENT": "production",
    "KORPUS_AUTH_MODE": "oidc",
    "KORPUS_BROWSER_AUTH_ENABLED": "true",
    "KORPUS_SCHEMA_MODE": "migrations",
    "KORPUS_INGESTION_MODE": "durable_async",
    "KORPUS_ANSWER_POLICY_MODE": "calibrated",
    "KORPUS_REQUIRE_SOURCE_SIGNATURES": "true",
    "KORPUS_ENTITLEMENT_PROFILE_PATH": "/etc/korpus/governance/entitlements.json",
    "KORPUS_SOURCE_TRUST_PROFILE_PATH": "/etc/korpus/governance/source-trust.json",
    "KORPUS_REVIEWER_REGISTRY_PATH": "/etc/korpus/governance/reviewers.json",
    "KORPUS_CORPUS_GOVERNANCE_PROFILE_PATH": "/etc/korpus/governance/corpus-governance.json",
}
