"""Render deployment overlays and state the security predicates over the result.

Destruction stage 2026-08-03: ``validate_kubernetes.py`` read
``deploy/kubernetes/base/*.yaml`` and nothing else. The production overlay — the
thing that is actually applied to a cluster — was never rendered, so a patch that
set ``image: …:latest`` and ``readOnlyRootFilesystem: false`` passed all three
validators. A gate over inputs that are not deployed is a gate over nothing.

Rendering is done here rather than by shelling out to ``kustomize`` because the
validator has to run wherever the pipeline runs, including images that carry only
Python. The supported subset is exactly what this repository uses — ``resources``,
``namespace``, and ``patches`` in both JSON-6902 and strategic-merge form — and an
unsupported field is an error rather than a silent skip: a patch this renderer
ignores is a patch the gate cannot see.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

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


class RenderError(ValueError):
    """Raised when a kustomization cannot be rendered exactly."""


def _load_documents(path: Path) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for item in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        if isinstance(item, dict):
            documents.append(item)
    return documents


def _matches(document: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    if "kind" in target and document.get("kind") != target["kind"]:
        return False
    name = document.get("metadata", {}).get("name")
    return not ("name" in target and name != target["name"])


def _navigate(document: Any, pointer: str) -> tuple[Any, str | int]:
    """Resolve a JSON pointer to (container, key), creating nothing."""

    if not pointer.startswith("/"):
        raise RenderError(f"malformed JSON pointer: {pointer!r}")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]
    current = document
    for part in parts[:-1]:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            if part not in current:
                raise RenderError(f"pointer {pointer!r} does not resolve")
            current = current[part]
    last = parts[-1]
    if isinstance(current, list):
        return current, (len(current) if last == "-" else int(last))
    return current, last


def _apply_json6902(document: dict[str, Any], operations: Sequence[Mapping[str, Any]]) -> None:
    for operation in operations:
        kind = operation.get("op")
        path = str(operation.get("path", ""))
        container, key = _navigate(document, path)
        if kind == "replace":
            if isinstance(container, list):
                container[int(key)] = operation["value"]
            else:
                if key not in container:
                    raise RenderError(f"replace on absent path {path!r}")
                container[key] = operation["value"]
        elif kind == "add":
            if isinstance(container, list):
                container.insert(int(key), operation["value"])
            else:
                container[key] = operation["value"]
        elif kind == "remove":
            if isinstance(container, list):
                del container[int(key)]
            else:
                container.pop(key, None)
        else:
            raise RenderError(f"unsupported patch operation: {kind!r}")


def _strategic_merge(base: dict[str, Any], patch: Mapping[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _strategic_merge(base[key], value)
        elif isinstance(value, list) and isinstance(base.get(key), list):
            merged = list(base[key])
            for index, item in enumerate(value):
                if index < len(merged) and isinstance(item, Mapping) and isinstance(
                    merged[index], dict
                ):
                    _strategic_merge(merged[index], item)
                elif index < len(merged):
                    merged[index] = item
                else:
                    merged.append(item)
            base[key] = merged
        else:
            base[key] = value


def render_kustomization(directory: Path, root: Path | None = None) -> list[dict[str, Any]]:
    """Render one kustomization directory into its final document list."""

    root = root or directory
    kustomization = directory / "kustomization.yaml"
    if not kustomization.is_file():
        raise RenderError(f"no kustomization.yaml in {directory}")
    spec = yaml.safe_load(kustomization.read_text(encoding="utf-8")) or {}
    unsupported = set(spec) - SUPPORTED_KUSTOMIZATION_FIELDS
    if unsupported:
        raise RenderError(
            f"{directory}: unsupported kustomization fields {sorted(unsupported)} — the "
            "validator would silently ignore them, so it must refuse instead"
        )

    documents: list[dict[str, Any]] = []
    for resource in spec.get("resources", []):
        target = (directory / str(resource)).resolve()
        if target.is_dir():
            documents.extend(render_kustomization(target, root))
            continue
        if not target.is_file():
            raise RenderError(f"{directory}: resource {resource!r} does not exist")
        for loaded in _load_documents(target):
            document = copy.deepcopy(loaded)
            document["__file__"] = (
                str(target.relative_to(root)) if target.is_relative_to(root) else str(target)
            )
            documents.append(document)

    namespace = spec.get("namespace")
    if namespace:
        for document in documents:
            if document.get("kind") == "Namespace":
                continue
            document.setdefault("metadata", {})["namespace"] = namespace

    for patch in spec.get("patches", []):
        target = patch.get("target", {})
        body = yaml.safe_load(patch["patch"]) if isinstance(patch.get("patch"), str) else None
        if body is None:
            raise RenderError(f"{directory}: patch without an inline body is not supported")
        selected = [document for document in documents if _matches(document, target)]
        if not selected:
            raise RenderError(f"{directory}: patch target {target} matches no resource")
        for document in selected:
            if isinstance(body, list):
                _apply_json6902(document, body)
            elif isinstance(body, Mapping):
                _strategic_merge(document, dict(body))
            else:
                raise RenderError(f"{directory}: unreadable patch body")
    return documents


def discover_kustomizations(deploy_root: Path) -> list[Path]:
    """Every directory that can be applied to a cluster, base and overlays alike."""

    return sorted(path.parent for path in deploy_root.rglob("kustomization.yaml"))


def _workload_violations(resource: Mapping[str, Any]) -> list[str]:
    name = resource.get("metadata", {}).get("name", "<unnamed>")
    pod_spec = resource.get("spec", {}).get("template", {}).get("spec", {})
    problems: list[str] = []
    if pod_spec.get("automountServiceAccountToken") is not False:
        problems.append(f"{name}: service-account token must be disabled")
    pod_security = pod_spec.get("securityContext", {})
    if (
        pod_security.get("runAsNonRoot") is not True
        or pod_security.get("seccompProfile", {}).get("type") != "RuntimeDefault"
    ):
        problems.append(f"{name}: restricted pod security missing")
    containers = pod_spec.get("containers", [])
    if not containers:
        problems.append(f"{name}: no containers")
    for container in containers:
        image = str(container.get("image", ""))
        if "@sha256:" not in image:
            problems.append(f"{name}: image must be digest-addressed, got {image!r}")
        security = container.get("securityContext", {})
        if security.get("allowPrivilegeEscalation") is not False:
            problems.append(f"{name}: privilege escalation must be disabled")
        if security.get("readOnlyRootFilesystem") is not True:
            problems.append(f"{name}: root filesystem must be read-only")
        if security.get("capabilities", {}).get("drop") != ["ALL"]:
            problems.append(f"{name}: all capabilities must be dropped")
        resources = container.get("resources", {})
        if not resources.get("requests") or not resources.get("limits"):
            problems.append(f"{name}: resource requests/limits required")
    return problems


def manifest_violations(documents: Iterable[Mapping[str, Any]]) -> list[str]:
    """State the deployment invariants over a *rendered* document set."""

    documents = list(documents)
    if not documents:
        return ["no Kubernetes resources"]
    by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for document in documents:
        by_kind.setdefault(str(document.get("kind")), []).append(document)

    problems: list[str] = []
    missing = REQUIRED_KINDS - set(by_kind)
    if missing:
        problems.append(f"missing Kubernetes resource kinds: {sorted(missing)}")

    namespaces = by_kind.get("Namespace", [])
    if namespaces:
        labels = namespaces[0].get("metadata", {}).get("labels", {})
        if labels.get("pod-security.kubernetes.io/enforce") != "restricted":
            problems.append("namespace must enforce restricted Pod Security")

    workload_names = set()
    for resource in [*by_kind.get("Deployment", []), *by_kind.get("Job", [])]:
        workload_names.add(resource.get("metadata", {}).get("name"))
        problems.extend(_workload_violations(resource))
    absent = REQUIRED_WORKLOADS - workload_names
    if absent:
        problems.append(f"required workloads missing: {sorted(absent)}")

    if not any(
        policy.get("metadata", {}).get("name") == "default-deny"
        and policy.get("spec", {}).get("podSelector") == {}
        for policy in by_kind.get("NetworkPolicy", [])
    ):
        problems.append("default-deny NetworkPolicy missing")

    configmaps = by_kind.get("ConfigMap", [])
    config = configmaps[0].get("data", {}) if configmaps else {}
    for key, value in REQUIRED_PRODUCTION_CONFIG.items():
        if config.get(key) != value:
            problems.append(f"secure production config missing: {key}={value}")

    for workload in ("korpus-api", "korpus-worker"):
        deployment = next(
            (
                item
                for item in by_kind.get("Deployment", [])
                if item.get("metadata", {}).get("name") == workload
            ),
            None,
        )
        if deployment is None:
            continue
        pod_spec = deployment.get("spec", {}).get("template", {}).get("spec", {})
        volumes = {volume.get("name"): volume for volume in pod_spec.get("volumes", [])}
        governance = volumes.get("governance", {}).get("secret", {})
        if governance.get("secretName") != "korpus-governance-bundle":
            problems.append(f"{workload}: content-addressed governance secret volume missing")
        containers = pod_spec.get("containers", [])
        mounts = containers[0].get("volumeMounts", []) if containers else []
        if not any(
            mount.get("name") == "governance"
            and mount.get("mountPath") == "/etc/korpus/governance"
            and mount.get("readOnly") is True
            for mount in mounts
        ):
            problems.append(f"{workload}: governance bundle must be mounted read-only")
    return problems
