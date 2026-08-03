#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "deploy/kubernetes/base"


def documents() -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for path in sorted(BASE.glob("*.yaml")):
        for item in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if isinstance(item, dict):
                item["__file__"] = str(path.relative_to(ROOT))
                output.append(item)
    return output


def fail(message: str) -> None:
    raise SystemExit(message)


def main() -> None:
    docs = documents()
    if not docs:
        fail("no Kubernetes resources")
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        by_kind.setdefault(str(doc.get("kind")), []).append(doc)
    required = {
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
    missing = required - set(by_kind)
    if missing:
        fail(f"missing Kubernetes resource kinds: {sorted(missing)}")

    namespace = by_kind["Namespace"][0]
    labels = namespace.get("metadata", {}).get("labels", {})
    if labels.get("pod-security.kubernetes.io/enforce") != "restricted":
        fail("namespace must enforce restricted Pod Security")

    deployment_names = set()
    for resource in [*by_kind["Deployment"], *by_kind["Job"]]:
        metadata = resource.get("metadata", {})
        deployment_names.add(metadata.get("name"))
        template = resource.get("spec", {}).get("template", {})
        pod_spec = template.get("spec", {})
        if pod_spec.get("automountServiceAccountToken") is not False:
            fail(f"{metadata.get('name')}: service-account token must be disabled")
        pod_security = pod_spec.get("securityContext", {})
        if (
            pod_security.get("runAsNonRoot") is not True
            or pod_security.get("seccompProfile", {}).get("type") != "RuntimeDefault"
        ):
            fail(f"{metadata.get('name')}: restricted pod security missing")
        containers = pod_spec.get("containers", [])
        if not containers:
            fail(f"{metadata.get('name')}: no containers")
        for container in containers:
            image = str(container.get("image", ""))
            if "@sha256:" not in image:
                fail(f"{metadata.get('name')}: image must be digest-addressed")
            security = container.get("securityContext", {})
            if security.get("allowPrivilegeEscalation") is not False:
                fail(f"{metadata.get('name')}: privilege escalation must be disabled")
            if security.get("readOnlyRootFilesystem") is not True:
                fail(f"{metadata.get('name')}: root filesystem must be read-only")
            if security.get("capabilities", {}).get("drop") != ["ALL"]:
                fail(f"{metadata.get('name')}: all capabilities must be dropped")
            resources = container.get("resources", {})
            if not resources.get("requests") or not resources.get("limits"):
                fail(f"{metadata.get('name')}: resource requests/limits required")
    if {"korpus-api", "korpus-worker", "korpus-web"} - deployment_names:
        fail("API, worker and web deployments are required")

    policies = by_kind["NetworkPolicy"]
    if not any(
        policy.get("metadata", {}).get("name") == "default-deny"
        and policy.get("spec", {}).get("podSelector") == {}
        for policy in policies
    ):
        fail("default-deny NetworkPolicy missing")
    config = by_kind["ConfigMap"][0].get("data", {})
    expected = {
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
    for key, value in expected.items():
        if config.get(key) != value:
            fail(f"secure production config missing: {key}={value}")

    for deployment_name in ("korpus-api", "korpus-worker"):
        deployment = next(
            item for item in by_kind["Deployment"]
            if item.get("metadata", {}).get("name") == deployment_name
        )
        pod_spec = deployment["spec"]["template"]["spec"]
        volumes = {volume.get("name"): volume for volume in pod_spec.get("volumes", [])}
        governance = volumes.get("governance", {}).get("secret", {})
        if governance.get("secretName") != "korpus-governance-bundle":
            fail(f"{deployment_name}: content-addressed governance secret volume missing")
        mounts = pod_spec["containers"][0].get("volumeMounts", [])
        if not any(
            mount.get("name") == "governance"
            and mount.get("mountPath") == "/etc/korpus/governance"
            and mount.get("readOnly") is True
            for mount in mounts
        ):
            fail(f"{deployment_name}: governance bundle must be mounted read-only")

    report = {
        "status": "PASS",
        "resources": len(docs),
        "kinds": {key: len(value) for key, value in sorted(by_kind.items())},
        "note": "static topology validation only; cluster execution remains external evidence",
    }
    output = ROOT / "var/kubernetes-validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
