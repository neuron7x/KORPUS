"""The deployment invariants as a register, one entry per property.

The fourth and last of the validators `application/requirements.py` was written for.
`manifest_violations` was the same shape as the other three: a run of
`if …: problems.append("…")`, where a check's only identity is the sentence it appends.
Three consequences follow, and none of them is about how long the function was.

*A failure cannot be named.* A report says "korpus-api: root filesystem must be
read-only" and nothing connects that sentence to a rule an assessor can look up, an
owner can mark accepted-with-risk, or a register can count.

*A mutant cannot reach one check.* The catalogue works by editing a line and demanding a
test die. With twenty checks in one function a mutant hits the function or nothing.

*The rules cannot be read.* What a deployment must satisfy before it may run is a
document somebody signs, not a program whose execution happens to emit the list.

Per-workload requirements are generated rather than written out, because the properties
are the same for every workload and the workload set changes. Their ids carry the
workload and container index — `k8s.workload.korpus-api.container.0.read_only_root` —
so a failure names one container of one workload rather than a category.

A requirement carries two sentences. `statement` is positive — what a compliant
deployment looks like — because a register is read start to finish and a list of
negations is read wrong under pressure. `failure` is what an operator is told, verbatim
from the inline version, and it can name what was actually found. Fifteen negative
controls in `test_deployment_rendering_refusals.py` assert on those sentences and were
written before this move; their passing unchanged is what makes this a refactor rather
than a rewrite with the tests adjusted to fit.

The three constants — required kinds, required workloads, required production config —
stay in `application/deployment.py` and are imported. Restating them here is how a
register ends up gating a smaller set than the deployment actually needs, and the first
draft of this file did exactly that: it named five kinds where the deployment names
nine, and dropped seven of the eleven required config keys.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from korpus.application.deployment_contract import (
    REQUIRED_KINDS,
    REQUIRED_PRODUCTION_CONFIG,
    REQUIRED_WORKLOADS,
)
from korpus.application.requirements import Requirement, evaluate_requirements

#: Workloads that mount the governance bundle. Not every workload does: `korpus-migrate`
#: runs before the corpus exists and has nothing to govern.
GOVERNED_WORKLOADS = ("korpus-api", "korpus-worker")


@dataclass(frozen=True)
class KubernetesContext:
    """The rendered document set, indexed once.

    Indexing here rather than inside each predicate keeps a register of twenty
    requirements from walking the document list twenty times, and — more to the point —
    keeps every predicate reading the same view. A predicate that re-derived `by_kind`
    could disagree with its neighbour about what was rendered.
    """

    documents: tuple[Mapping[str, Any], ...]
    by_kind: dict[str, list[Mapping[str, Any]]] = field(default_factory=dict)

    @classmethod
    def build(cls, documents: Iterable[Mapping[str, Any]]) -> KubernetesContext:
        listed = tuple(documents)
        by_kind: dict[str, list[Mapping[str, Any]]] = {}
        for document in listed:
            by_kind.setdefault(str(document.get("kind")), []).append(document)
        return cls(documents=listed, by_kind=by_kind)

    @property
    def workloads(self) -> list[Mapping[str, Any]]:
        return [*self.by_kind.get("Deployment", []), *self.by_kind.get("Job", [])]

    def workload_named(self, name: str) -> Mapping[str, Any] | None:
        return next(
            (
                item
                for item in self.by_kind.get("Deployment", [])
                if item.get("metadata", {}).get("name") == name
            ),
            None,
        )

    @property
    def config(self) -> Mapping[str, Any]:
        configmaps = self.by_kind.get("ConfigMap", [])
        return configmaps[0].get("data", {}) if configmaps else {}


def _pod_spec(resource: Mapping[str, Any]) -> Mapping[str, Any]:
    spec: Mapping[str, Any] = resource.get("spec", {}).get("template", {}).get("spec", {})
    return spec


def _name(resource: Mapping[str, Any]) -> str:
    return str(resource.get("metadata", {}).get("name", "<unnamed>"))


def _cluster_requirements(context: KubernetesContext) -> tuple[Requirement, ...]:
    return (
        Requirement(
            id="k8s.cluster.resources_rendered",
            subject="deployment",
            statement="the kustomization renders at least one resource",
            failure="no Kubernetes resources",
            rationale=(
                "rendering nothing and rendering something compliant must not look "
                "alike; an empty result is the most permissive possible output"
            ),
            holds=lambda context: bool(context.documents),
        ),
        Requirement(
            id="k8s.cluster.required_kinds",
            subject="deployment",
            statement=f"every required resource kind is rendered: {sorted(REQUIRED_KINDS)}",
            failure=(
                "missing Kubernetes resource kinds: "
                f"{sorted(REQUIRED_KINDS - set(context.by_kind))}"
            ),
            rationale="a deployment without a NetworkPolicy or a Namespace is not one",
            holds=lambda context: not (REQUIRED_KINDS - set(context.by_kind)),
        ),
        Requirement(
            id="k8s.namespace.restricted_pod_security",
            subject="Namespace",
            statement="the namespace enforces restricted Pod Security",
            failure="namespace must enforce restricted Pod Security",
            rationale=(
                "the namespace label is what a cluster enforces when a workload's own "
                "security context is wrong; without it every per-container check here "
                "is the only line of defence"
            ),
            holds=lambda context: (
                not context.by_kind.get("Namespace", [])
                or context.by_kind["Namespace"][0]
                .get("metadata", {})
                .get("labels", {})
                .get("pod-security.kubernetes.io/enforce")
                == "restricted"
            ),
        ),
        Requirement(
            id="k8s.cluster.required_workloads",
            subject="deployment",
            statement=f"every required workload is rendered: {sorted(REQUIRED_WORKLOADS)}",
            failure=(
                "required workloads missing: "
                f"{sorted(REQUIRED_WORKLOADS - {_name(item) for item in context.workloads})}"
            ),
            rationale=(
                "a rendered set missing a workload deploys a system with a piece of "
                "itself absent, and nothing at runtime reports the absence"
            ),
            holds=lambda context: not (
                REQUIRED_WORKLOADS - {_name(item) for item in context.workloads}
            ),
        ),
        Requirement(
            id="k8s.network.default_deny",
            subject="NetworkPolicy",
            statement="a default-deny NetworkPolicy with an empty podSelector exists",
            failure="default-deny NetworkPolicy missing",
            rationale=(
                "without an empty podSelector denying everything first, every later "
                "policy is an addition to an open network rather than an exception to a "
                "closed one"
            ),
            holds=lambda context: any(
                policy.get("metadata", {}).get("name") == "default-deny"
                and policy.get("spec", {}).get("podSelector") == {}
                for policy in context.by_kind.get("NetworkPolicy", [])
            ),
        ),
    )


def _config_requirements() -> tuple[Requirement, ...]:
    def check(key: str, value: str) -> Callable[[KubernetesContext], bool]:
        return lambda context: context.config.get(key) == value

    return tuple(
        Requirement(
            id=f"k8s.config.{key.lower()}",
            subject="ConfigMap",
            statement=f"the deployed configuration carries {key}={value}",
            failure=f"secure production config missing: {key}={value}",
            rationale=(
                "the deployed configuration is what runs; a controlled environment that "
                "ships dev auth or automatic schema creation is not the one that was "
                "reviewed"
            ),
            holds=check(key, value),
        )
        for key, value in REQUIRED_PRODUCTION_CONFIG.items()
    )


def _pod_requirements(resource: Mapping[str, Any]) -> tuple[Requirement, ...]:
    name = _name(resource)

    def pod_security_ok(context: KubernetesContext) -> bool:
        security = _pod_spec(resource).get("securityContext", {})
        return (
            security.get("runAsNonRoot") is True
            and security.get("seccompProfile", {}).get("type") == "RuntimeDefault"
        )

    return (
        Requirement(
            id=f"k8s.workload.{name}.no_service_account_token",
            subject=name,
            statement=f"{name}: the service-account token is not mounted",
            failure=f"{name}: service-account token must be disabled",
            rationale=(
                "a mounted token is a cluster credential inside a process that parses "
                "untrusted documents"
            ),
            holds=lambda context: _pod_spec(resource).get("automountServiceAccountToken")
            is False,
        ),
        Requirement(
            id=f"k8s.workload.{name}.restricted_pod_security",
            subject=name,
            statement=f"{name}: the pod runs non-root under the RuntimeDefault seccomp profile",
            failure=f"{name}: restricted pod security missing",
            rationale="runAsNonRoot and RuntimeDefault seccomp are the pod-level floor",
            holds=pod_security_ok,
        ),
        Requirement(
            id=f"k8s.workload.{name}.has_containers",
            subject=name,
            statement=f"{name}: the pod declares at least one container",
            failure=f"{name}: no containers",
            rationale=(
                "a workload with no containers passes every per-container check below "
                "vacuously, which is the shape of a hardening step that was deleted"
            ),
            holds=lambda context: bool(_pod_spec(resource).get("containers", [])),
        ),
    )


def _container_requirements(
    resource: Mapping[str, Any], index: int, container: Mapping[str, Any]
) -> tuple[Requirement, ...]:
    name = _name(resource)
    prefix = f"k8s.workload.{name}.container.{index}"
    image = str(container.get("image", ""))
    security = container.get("securityContext", {})
    resources = container.get("resources", {})

    return (
        Requirement(
            id=f"{prefix}.image_digest",
            subject=name,
            statement=f"{name}: the container image is pinned by digest",
            failure=f"{name}: image must be digest-addressed, got {image!r}",
            rationale=(
                "a tag is a name the registry may repoint at any time; a digest is the "
                "bytes. An overlay patching in `:latest` passed this gate until "
                "2026-08-04, because overlays were never rendered"
            ),
            holds=lambda context: "@sha256:" in image,
        ),
        Requirement(
            id=f"{prefix}.no_privilege_escalation",
            subject=name,
            statement=f"{name}: the container cannot escalate privilege",
            failure=f"{name}: privilege escalation must be disabled",
            rationale="setuid inside the container defeats the non-root pod context",
            holds=lambda context: security.get("allowPrivilegeEscalation") is False,
        ),
        Requirement(
            id=f"{prefix}.read_only_root",
            subject=name,
            statement=f"{name}: the container root filesystem is read-only",
            failure=f"{name}: root filesystem must be read-only",
            rationale="a writable root is where an uploaded document becomes an executable",
            holds=lambda context: security.get("readOnlyRootFilesystem") is True,
        ),
        Requirement(
            id=f"{prefix}.all_capabilities_dropped",
            subject=name,
            statement=f"{name}: the container drops every capability",
            failure=f"{name}: all capabilities must be dropped",
            rationale=(
                "dropping a named subset leaves the rest; the destruction stage on "
                "2026-08-03 got past this with `drop: [NET_RAW]`"
            ),
            holds=lambda context: security.get("capabilities", {}).get("drop") == ["ALL"],
        ),
        Requirement(
            id=f"{prefix}.resource_bounds",
            subject=name,
            statement=f"{name}: the container declares resource requests and limits",
            failure=f"{name}: resource requests/limits required",
            rationale=(
                "an unbounded container is the cheapest denial of service in the "
                "cluster, available to whoever uploads the largest document"
            ),
            holds=lambda context: bool(resources.get("requests"))
            and bool(resources.get("limits")),
        ),
    )


def _governance_requirements(name: str, deployment: Mapping[str, Any]) -> tuple[Requirement, ...]:
    pod_spec = _pod_spec(deployment)
    volumes = {volume.get("name"): volume for volume in pod_spec.get("volumes", [])}
    containers = pod_spec.get("containers", [])
    mounts = containers[0].get("volumeMounts", []) if containers else []

    return (
        Requirement(
            id=f"k8s.workload.{name}.governance_volume",
            subject=name,
            statement=f"{name}: the governance bundle is supplied as a named secret volume",
            failure=f"{name}: content-addressed governance secret volume missing",
            rationale=(
                "the governance bundle carries the entitlement profile and its digest; "
                "a workload without it falls back to whatever is on disk"
            ),
            holds=lambda context: volumes.get("governance", {}).get("secret", {}).get(
                "secretName"
            )
            == "korpus-governance-bundle",
        ),
        Requirement(
            id=f"k8s.workload.{name}.governance_read_only",
            subject=name,
            statement=f"{name}: the governance bundle is mounted read-only at its expected path",
            failure=f"{name}: governance bundle must be mounted read-only",
            rationale=(
                "a writable entitlement profile is an entitlement profile the process "
                "that reads it can also edit"
            ),
            holds=lambda context: any(
                mount.get("name") == "governance"
                and mount.get("mountPath") == "/etc/korpus/governance"
                and mount.get("readOnly") is True
                for mount in mounts
            ),
        ),
    )


def kubernetes_requirements(context: KubernetesContext) -> tuple[Requirement, ...]:
    """The whole register for one rendered document set.

    Order matches the inline version exactly. It is not decoration: an operator reads
    the first failure, and a set that reports "no containers" before "image must be
    digest-addressed" is telling them which problem to solve first.
    """
    requirements: list[Requirement] = []
    cluster = _cluster_requirements(context)
    # `resources_rendered` short-circuits: with nothing rendered, every other
    # requirement below would fail too, and twenty failures describing an empty input
    # is a report nobody reads to the end.
    if not context.documents:
        return (cluster[0],)

    requirements.extend(cluster[1:3])
    for workload in context.workloads:
        requirements.extend(_pod_requirements(workload))
        for index, container in enumerate(_pod_spec(workload).get("containers", [])):
            requirements.extend(_container_requirements(workload, index, container))
    requirements.extend(cluster[3:])
    requirements.extend(_config_requirements())
    for name in GOVERNED_WORKLOADS:
        deployment = context.workload_named(name)
        if deployment is not None:
            requirements.extend(_governance_requirements(name, deployment))
    return tuple(requirements)


def manifest_violations(documents: Iterable[Mapping[str, Any]]) -> list[str]:
    """The deployment invariants over a *rendered* document set, as operator sentences.

    The register is the source; this is the projection the gate and its fifteen negative
    controls have always consumed.
    """
    context = KubernetesContext.build(documents)
    report = evaluate_requirements(kubernetes_requirements(context), context)
    return [requirement.message for requirement in report.unmet]
