from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/gcp"))
from production_inputs import validate  # noqa: E402


def good() -> dict[str, str]:
    return {
        "GCP_PROJECT_ID": "korpus-prod-12345",
        "TF_STATE_BUCKET": "korpus-prod-12345-tfstate",
        "DOMAIN": "korpus.example.com",
        "WIF_PROVIDER": "projects/123456789/locations/global/workloadIdentityPools/korpus-runtime/providers/github",
        "DEPLOYER_SA": "korpus-runtime@korpus-prod-12345.iam.gserviceaccount.com",
        "OIDC_ISSUER": "https://identity.example.com/realms/korpus",
        "OIDC_JWKS_URL": "https://identity.example.com/realms/korpus/certs",
        "OIDC_AUTH_ENDPOINT": "https://identity.example.com/realms/korpus/auth?tenant=korpus",
        "OIDC_TOKEN_ENDPOINT": "https://identity.example.com/realms/korpus/token",
        "OIDC_END_SESSION_ENDPOINT": "https://identity.example.com/realms/korpus/logout",
        "OIDC_CLIENT_ID": "korpus-web",
        "OIDC_AUDIENCE": "korpus-api",
        "CLAMAV_SOURCE_IMAGE": "docker.io/clamav/clamav@sha256:" + "a" * 64,
        "MONITORING_CHANNELS": '["projects/korpus-prod-12345/notificationChannels/123"]',
        "DATABASE_DISK_AUTOSIZE_LIMIT_GB": "200",
        "OTLP_ENDPOINT": "https://otel.example.com/v1/traces",
    }


def test_valid_external_inputs_pass() -> None:
    report = validate(good())
    assert report.values["domain"] == "korpus.example.com"
    assert report.values["clamav_source_digest_pinned"] is True


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("DOMAIN", "HTTPS://evil"),
        ("OIDC_ISSUER", "https://user:pass@identity.example.com"),
        ("OIDC_ISSUER", "https://identity.example.com/?shadow=1"),
        ("OIDC_JWKS_URL", "https://identity.example.com/certs#fragment"),
        ("OIDC_TOKEN_ENDPOINT", "http://identity.example.com/token"),
        ("WIF_PROVIDER", "projects/x/locations/global/workloadIdentityPools/p/providers/q"),
        ("DEPLOYER_SA", "owner@example.com"),
        ("CLAMAV_SOURCE_IMAGE", "docker.io/clamav/clamav:latest"),
        ("MONITORING_CHANNELS", "[]"),
        ("DATABASE_DISK_AUTOSIZE_LIMIT_GB", "0"),
        ("DATABASE_DISK_AUTOSIZE_LIMIT_GB", "unbounded"),
    ],
)
def test_unsafe_external_input_is_refused(name: str, bad: str) -> None:
    values = good(); values[name] = bad
    with pytest.raises(ValueError):
        validate(values)
