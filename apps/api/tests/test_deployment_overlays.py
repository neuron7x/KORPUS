"""What is deployed must be what is validated.

Destruction stage 2026-08-03: the production overlay was never rendered, so a
patch that set ``image: …:latest`` and ``readOnlyRootFilesystem: false`` passed
all three validators. These tests apply that exact patch and require the gate to
go red, and require every applyable variant in the repository to be covered.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from korpus.application.deployment import (
    RenderError,
    discover_kustomizations,
    manifest_violations,
    render_kustomization,
)

ROOT = Path(__file__).resolve().parents[3]
DEPLOY_ROOT = ROOT / "deploy/kubernetes"
PRODUCTION = DEPLOY_ROOT / "overlays/production"

HOSTILE_PATCH = """
  - target: {kind: Deployment, name: korpus-api}
    patch: |-
      - op: replace
        path: /spec/template/spec/containers/0/image
        value: registry.example.com/korpus/api:latest
      - op: replace
        path: /spec/template/spec/containers/0/securityContext/readOnlyRootFilesystem
        value: false
"""


def test_the_repository_ships_a_production_overlay_that_is_validated() -> None:
    variants = discover_kustomizations(DEPLOY_ROOT)
    names = {path.relative_to(DEPLOY_ROOT).as_posix() for path in variants}
    assert "base" in names
    assert "overlays/production" in names, (
        "the production overlay disappeared from discovery; a variant that is applied "
        "but not discovered is a variant with no gate"
    )


def test_every_shipped_variant_renders_and_satisfies_the_policy() -> None:
    for directory in discover_kustomizations(DEPLOY_ROOT):
        documents = render_kustomization(directory, ROOT)
        assert manifest_violations(documents) == [], directory


def test_a_hostile_overlay_patch_is_caught(tmp_path: Path) -> None:
    """The reproduction: :latest plus a writable root filesystem, via the overlay."""

    overlay = tmp_path / "kustomization.yaml"
    text = (PRODUCTION / "kustomization.yaml").read_text(encoding="utf-8")
    resources_path = (PRODUCTION / "../../base").resolve()
    text = text.replace("  - ../../base", f"  - {resources_path}")
    overlay.write_text(text + HOSTILE_PATCH, encoding="utf-8")

    documents = render_kustomization(tmp_path, ROOT)
    violations = manifest_violations(documents)
    assert any("digest-addressed" in violation for violation in violations), violations
    assert any("read-only" in violation for violation in violations), violations


def test_the_overlay_actually_changes_the_rendered_output() -> None:
    """A renderer that ignored patches would also report zero violations."""

    base = {
        document["metadata"]["name"]: document
        for document in render_kustomization(DEPLOY_ROOT / "base", ROOT)
        if document.get("kind") == "Deployment"
    }
    rendered = {
        document["metadata"]["name"]: document
        for document in render_kustomization(PRODUCTION, ROOT)
        if document.get("kind") == "Deployment"
    }
    assert base["korpus-api"]["spec"]["replicas"] != rendered["korpus-api"]["spec"]["replicas"]
    assert rendered["korpus-api"]["spec"]["replicas"] == 3
    assert rendered["korpus-api"]["metadata"]["namespace"] == "korpus"


def test_an_unsupported_kustomization_field_is_refused(tmp_path: Path) -> None:
    """A field the renderer ignores is a field the gate cannot see."""

    (tmp_path / "kustomization.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "kustomize.config.k8s.io/v1beta1",
                "kind": "Kustomization",
                "resources": [],
                "images": [{"name": "api", "newTag": "latest"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RenderError, match="unsupported kustomization fields"):
        render_kustomization(tmp_path, ROOT)


def test_a_patch_matching_nothing_is_refused(tmp_path: Path) -> None:
    """Silently dropping a patch makes the rendered set differ from the cluster."""

    (tmp_path / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\n"
        "kind: Kustomization\n"
        "resources: []\n"
        "patches:\n"
        "  - target: {kind: Deployment, name: does-not-exist}\n"
        "    patch: |-\n"
        "      - op: replace\n"
        "        path: /spec/replicas\n"
        "        value: 9\n",
        encoding="utf-8",
    )
    with pytest.raises(RenderError, match="matches no resource"):
        render_kustomization(tmp_path, ROOT)


def test_strategic_merge_patches_are_applied(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    (base_dir / "deployment.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": "korpus-api"},
                "spec": {"replicas": 1, "template": {"spec": {"containers": [{"name": "api"}]}}},
            }
        ),
        encoding="utf-8",
    )
    (base_dir / "kustomization.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "kustomize.config.k8s.io/v1beta1",
                "kind": "Kustomization",
                "resources": ["deployment.yaml"],
            }
        ),
        encoding="utf-8",
    )
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\n"
        "kind: Kustomization\n"
        "resources:\n"
        "  - ../base\n"
        "patches:\n"
        "  - target: {kind: Deployment, name: korpus-api}\n"
        "    patch: |-\n"
        "      spec:\n"
        "        replicas: 7\n",
        encoding="utf-8",
    )
    documents = render_kustomization(overlay, ROOT)
    assert documents[0]["spec"]["replicas"] == 7


def test_missing_workloads_are_reported() -> None:
    assert manifest_violations([]) == ["no Kubernetes resources"]
    partial = [{"kind": "Namespace", "metadata": {"name": "korpus"}}]
    violations = manifest_violations(partial)
    assert any("missing Kubernetes resource kinds" in violation for violation in violations)
    assert any("restricted Pod Security" in violation for violation in violations)


def test_the_validator_script_reports_every_variant() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/validate_kubernetes.py"],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "apps/api/src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert set(report["variants"]) == {"base", "overlays/production"}, report["variants"]
