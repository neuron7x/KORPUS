"""Keep scanner-compatible configuration equivalent at the runtime boundary."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from korpus.application.deployment import discover_kustomizations, render_kustomization

ROOT = Path(__file__).resolve().parents[3]
PUBLIC_KEY = "PUBLIC_OIDC_EXCHANGE_URL"
RUNTIME_KEY = "KORPUS_OIDC_TOKEN_ENDPOINT"


@pytest.mark.parametrize("variant", ["base", "overlays/production"])
def test_every_workload_resolves_public_oidc_url_to_existing_runtime_setting(variant: str) -> None:
    documents = render_kustomization(ROOT / "deploy/kubernetes" / variant, ROOT)
    configmaps = {
        doc["metadata"]["name"]: doc["data"] for doc in documents if doc["kind"] == "ConfigMap"
    }
    assert RUNTIME_KEY not in configmaps["korpus-config"]
    public_url = configmaps["korpus-config"][PUBLIC_KEY]
    parsed = urlsplit(public_url)
    assert parsed.scheme == "https" and parsed.hostname
    assert not (parsed.username or parsed.password or parsed.query or parsed.fragment)
    resolved = {}
    for doc in documents:
        if doc["kind"] not in {"Deployment", "Job"}:
            continue
        container = doc["spec"]["template"]["spec"]["containers"][0]
        if not any(
            item.get("configMapRef", {}).get("name") == "korpus-config"
            for item in container.get("envFrom", [])
        ):
            continue
        env = {item["name"]: item for item in container.get("env", [])}
        reference = env[RUNTIME_KEY]["valueFrom"]["configMapKeyRef"]
        resolved[doc["metadata"]["name"]] = configmaps[reference["name"]][reference["key"]]
        assert reference == {"name": "korpus-config", "key": PUBLIC_KEY}
        assert any("secretRef" in item for item in container["envFrom"])
    assert resolved == dict.fromkeys(("korpus-api", "korpus-worker", "korpus-migrate"), public_url)


def test_configmap_keeps_credentials_outside_the_public_url_mapping() -> None:
    for variant in discover_kustomizations(ROOT / "deploy/kubernetes"):
        for doc in render_kustomization(variant, ROOT):
            if doc["kind"] == "ConfigMap":
                assert not any(
                    marker in key
                    for key in doc["data"]
                    for marker in ("PASSWORD", "CLIENT_SECRET", "PRIVATE_KEY", "ACCESS_TOKEN")
                )


def test_cloudsql_client_certificate_policy_retains_connector_enforcement() -> None:
    foundation = (ROOT / "infra/gcp/foundation/main.tf").read_text()
    assert 'ssl_mode        = "TRUSTED_CLIENT_CERTIFICATE_REQUIRED"' in foundation
    assert 'connector_enforcement       = "REQUIRED"' in foundation
