"""The overlay renderer must refuse what it cannot see, and see what it renders.

Destruction stage 2026-08-03: `validate_kubernetes.py` read `deploy/kubernetes/base`
and nothing else, so an overlay patch setting `image: …:latest` and
`readOnlyRootFilesystem: false` passed all three validators. The renderer here exists
so the gate reads what is actually applied.

That makes its refusals load-bearing in a specific way: a patch the renderer silently
drops is a change the gate cannot see, so "unsupported" must raise rather than skip.
Those raise paths, and the workload predicates they feed, had no tests — the branches
existed and had never been taken.

Written against a fixture tree rather than the repository's own manifests, so the
tests state the renderer's contract instead of restating today's deployment.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from korpus.application.deployment import (
    RenderError,
    discover_kustomizations,
    manifest_violations,
    render_kustomization,
)

DEPLOYMENT = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {"name": "korpus-api"},
    "spec": {
        "template": {
            "spec": {
                "automountServiceAccountToken": False,
                "securityContext": {
                    "runAsNonRoot": True,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [
                    {
                        "name": "api",
                        "image": "registry.example/korpus@sha256:" + "a" * 64,
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "resources": {
                            "requests": {"cpu": "100m", "memory": "256Mi"},
                            "limits": {"cpu": "1", "memory": "1Gi"},
                        },
                    }
                ],
            }
        }
    },
}


def _base(tmp_path: Path, **kustomization: object) -> Path:
    directory = tmp_path / "base"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "deployment.yaml").write_text(yaml.safe_dump(DEPLOYMENT), encoding="utf-8")
    spec: dict[str, object] = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": ["deployment.yaml"],
    }
    spec.update(kustomization)
    (directory / "kustomization.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    return directory


def test_a_base_renders_to_the_documents_it_lists(tmp_path: Path) -> None:
    """The dual: the refusals below are only meaningful if rendering works."""
    documents = render_kustomization(_base(tmp_path))

    assert [document["kind"] for document in documents] == ["Deployment"]
    assert documents[0]["__file__"] == "deployment.yaml"


def test_a_directory_without_a_kustomization_is_refused(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()

    with pytest.raises(RenderError, match=r"no kustomization\.yaml"):
        render_kustomization(tmp_path / "empty")


def test_a_field_the_renderer_does_not_understand_is_refused(tmp_path: Path) -> None:
    """The whole point: an ignored field is a change the gate cannot see."""
    directory = _base(tmp_path, configMapGenerator=[{"name": "settings"}])

    with pytest.raises(RenderError, match="unsupported kustomization fields"):
        render_kustomization(directory)


def test_a_resource_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    directory = _base(tmp_path, resources=["deployment.yaml", "absent.yaml"])

    with pytest.raises(RenderError, match="does not exist"):
        render_kustomization(directory)


def test_a_namespace_is_applied_to_every_document_except_namespaces(tmp_path: Path) -> None:
    directory = _base(tmp_path, namespace="korpus-prod")
    namespace_document = {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": "korpus-prod"},
    }
    (directory / "namespace.yaml").write_text(yaml.safe_dump(namespace_document), encoding="utf-8")
    spec = yaml.safe_load((directory / "kustomization.yaml").read_text(encoding="utf-8"))
    spec["resources"] = ["namespace.yaml", "deployment.yaml"]
    (directory / "kustomization.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")

    documents = {d["kind"]: d for d in render_kustomization(directory)}

    assert documents["Deployment"]["metadata"]["namespace"] == "korpus-prod"
    assert "namespace" not in documents["Namespace"]["metadata"]


def _overlay(tmp_path: Path, patch: object, target: dict[str, object] | None = None) -> Path:
    _base(tmp_path)
    overlay = tmp_path / "overlay"
    overlay.mkdir(parents=True, exist_ok=True)
    spec = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": ["../base"],
        "patches": [
            {
                "target": target if target is not None else {"kind": "Deployment"},
                "patch": patch if isinstance(patch, str) else yaml.safe_dump(patch),
            }
        ],
    }
    (overlay / "kustomization.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    return overlay


def test_a_strategic_merge_patch_reaches_the_rendered_document(tmp_path: Path) -> None:
    overlay = _overlay(
        tmp_path,
        {
            "kind": "Deployment",
            "metadata": {"name": "korpus-api"},
            "spec": {"template": {"spec": {"containers": [{"name": "api", "image": "x:latest"}]}}},
        },
    )

    documents = render_kustomization(overlay, root=tmp_path)

    container = documents[0]["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "x:latest", "the overlay is what a cluster applies"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True, (
        "a merge must not drop the fields it does not mention"
    )


def test_a_json6902_replace_reaches_the_rendered_document(tmp_path: Path) -> None:
    overlay = _overlay(
        tmp_path,
        [
            {
                "op": "replace",
                "path": "/spec/template/spec/containers/0/image",
                "value": "registry.example/korpus@sha256:" + "b" * 64,
            }
        ],
    )

    documents = render_kustomization(overlay, root=tmp_path)

    assert documents[0]["spec"]["template"]["spec"]["containers"][0]["image"].endswith("b" * 64)


@pytest.mark.parametrize(
    "operations,reason",
    [
        ([{"op": "replace", "path": "spec/missing-slash", "value": 1}], "malformed JSON pointer"),
        ([{"op": "replace", "path": "/spec/nowhere/deeper", "value": 1}], "does not resolve"),
        ([{"op": "replace", "path": "/spec/absent", "value": 1}], "replace on absent path"),
        ([{"op": "merge", "path": "/spec", "value": 1}], "unsupported patch operation"),
    ],
)
def test_a_patch_the_renderer_cannot_apply_is_refused(
    operations: list[dict[str, object]], reason: str, tmp_path: Path
) -> None:
    overlay = _overlay(tmp_path, operations)

    with pytest.raises(RenderError, match=reason):
        render_kustomization(overlay, root=tmp_path)


def test_a_patch_that_selects_nothing_is_refused(tmp_path: Path) -> None:
    """Silently matching nothing is how an intended hardening step disappears."""
    overlay = _overlay(
        tmp_path,
        {"kind": "Deployment"},
        target={"kind": "Deployment", "name": "does-not-exist"},
    )

    with pytest.raises(RenderError, match="matches no resource"):
        render_kustomization(overlay, root=tmp_path)


def test_discovery_finds_base_and_overlay_alike(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path, {"kind": "Deployment"})

    found = discover_kustomizations(tmp_path)

    assert tmp_path / "base" in found
    assert overlay in found


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda pod: pod.update({"automountServiceAccountToken": True}), "service-account token"),
        (lambda pod: pod.update({"securityContext": {}}), "restricted pod security"),
        (lambda pod: pod.update({"containers": []}), "no containers"),
    ],
)
def test_a_pod_that_loosens_its_own_context_is_reported(mutation, reason: str) -> None:
    document = yaml.safe_load(yaml.safe_dump(DEPLOYMENT))
    mutation(document["spec"]["template"]["spec"])

    problems = manifest_violations([document])

    assert any(reason in problem for problem in problems), problems


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda c: c.update({"image": "registry.example/korpus:latest"}), "digest-addressed"),
        (
            lambda c: c["securityContext"].update({"allowPrivilegeEscalation": True}),
            "privilege escalation",
        ),
        (
            lambda c: c["securityContext"].update({"readOnlyRootFilesystem": False}),
            "root filesystem must be read-only",
        ),
        (
            lambda c: c["securityContext"].update({"capabilities": {"drop": ["NET_RAW"]}}),
            "capabilities must be dropped",
        ),
        (lambda c: c.update({"resources": {"requests": {"cpu": "1"}}}), "requests/limits"),
    ],
)
def test_a_container_that_loosens_its_own_context_is_reported(mutation, reason: str) -> None:
    """These are the exact loosenings the 2026-08-03 destruction stage got past."""
    document = yaml.safe_load(yaml.safe_dump(DEPLOYMENT))
    mutation(document["spec"]["template"]["spec"]["containers"][0])

    problems = manifest_violations([document])

    assert any(reason in problem for problem in problems), problems


def test_an_empty_document_set_is_a_violation_not_a_clean_result() -> None:
    """Rendering nothing and rendering something compliant must not look alike."""
    assert manifest_violations([]) != []
