#!/usr/bin/env python3
"""Fail-closed validation and OIDC discovery verification for external production inputs."""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")
DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
SA_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$")
WIF_RE = re.compile(r"^projects/[0-9]+/locations/global/workloadIdentityPools/[a-z0-9-]+/providers/[a-z0-9-]+$")
OCI_DIGEST_RE = re.compile(r"^[A-Za-z0-9._:-]+(?:/[A-Za-z0-9._-]+)+@sha256:[0-9a-f]{64}$")
CHANNEL_RE = re.compile(r"^projects/[^/]+/notificationChannels/[0-9]+$")


@dataclass(frozen=True)
class InputReport:
    values: dict[str, object]

def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "")
    if not value or value != value.strip():
        raise ValueError(f"{name} is required and must not contain surrounding whitespace")
    if any(token in value.lower() for token in ("<replace", "changeme", "example.invalid")):
        raise ValueError(f"{name} contains a placeholder")
    return value

def _https(value: str, *, name: str, allow_query: bool = True) -> str:
    if "\\" in value or any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise ValueError(f"{name} contains forbidden URL characters")
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError as exc:
        raise ValueError(f"{name} is malformed") from exc
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ValueError(f"{name} must be an absolute HTTPS URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"{name} must not contain URL credentials")
    if parts.fragment:
        raise ValueError(f"{name} must not contain a fragment")
    if not allow_query and parts.query:
        raise ValueError(f"{name} must not contain a query")
    return value

def _identity_inputs(values: Mapping[str, str]) -> dict[str, str]:
    project = _required(values, "GCP_PROJECT_ID")
    bucket = _required(values, "TF_STATE_BUCKET")
    domain = _required(values, "DOMAIN")
    wif = _required(values, "WIF_PROVIDER")
    sa = _required(values, "DEPLOYER_SA")
    if not PROJECT_RE.fullmatch(project):
        raise ValueError("GCP_PROJECT_ID is not a valid project-id shape")
    if not BUCKET_RE.fullmatch(bucket) or bucket.startswith("goog"):
        raise ValueError("TF_STATE_BUCKET is not a valid GCS bucket-name shape")
    if not DOMAIN_RE.fullmatch(domain) or domain != domain.lower():
        raise ValueError("DOMAIN must be a canonical lowercase DNS hostname")
    if not WIF_RE.fullmatch(wif):
        raise ValueError("WIF_PROVIDER must be a full Google Workload Identity Provider resource name")
    if not SA_RE.fullmatch(sa):
        raise ValueError("DEPLOYER_SA must be a Google service-account email")
    return {"project_id": project, "state_bucket": bucket, "domain": domain, "wif_provider": wif, "deployer_service_account": sa}

def _oidc_inputs(values: Mapping[str, str]) -> dict[str, object]:
    issuer = _https(_required(values, "OIDC_ISSUER"), name="OIDC_ISSUER", allow_query=False)
    jwks = _https(_required(values, "OIDC_JWKS_URL"), name="OIDC_JWKS_URL")
    auth = _https(_required(values, "OIDC_AUTH_ENDPOINT"), name="OIDC_AUTH_ENDPOINT")
    token = _https(_required(values, "OIDC_TOKEN_ENDPOINT"), name="OIDC_TOKEN_ENDPOINT")
    client_id = _required(values, "OIDC_CLIENT_ID")
    audience = _required(values, "OIDC_AUDIENCE")
    end_session = values.get("OIDC_END_SESSION_ENDPOINT", "").strip()
    if len(client_id) < 3 or len(audience) < 3:
        raise ValueError("OIDC client id and audience must be non-trivial")
    if end_session:
        _https(end_session, name="OIDC_END_SESSION_ENDPOINT")
    return {
        "issuer": issuer,
        "jwks_uri": jwks,
        "authorization_endpoint": auth,
        "token_endpoint": token,
        "end_session_endpoint": end_session,
        "client_id_present": True,
        "audience_present": True,
    }


def _delivery_inputs(values: Mapping[str, str]) -> dict[str, object]:
    clamav = _required(values, "CLAMAV_SOURCE_IMAGE")
    channels_raw = _required(values, "MONITORING_CHANNELS")
    otlp = values.get("OTLP_ENDPOINT", "").strip()
    disk_limit_raw = _required(values, "DATABASE_DISK_AUTOSIZE_LIMIT_GB")
    if not re.fullmatch(r"[1-9][0-9]*", disk_limit_raw):
        raise ValueError("DATABASE_DISK_AUTOSIZE_LIMIT_GB must be a positive integer GiB ceiling")
    disk_limit = int(disk_limit_raw)
    if not OCI_DIGEST_RE.fullmatch(clamav):
        raise ValueError("CLAMAV_SOURCE_IMAGE must be an OCI image pinned by sha256 digest")
    if otlp:
        _https(otlp, name="OTLP_ENDPOINT")
    try:
        channels = json.loads(channels_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("MONITORING_CHANNELS must be JSON") from exc
    valid_channels = isinstance(channels, list) and bool(channels) and all(
        isinstance(item, str) and CHANNEL_RE.fullmatch(item) for item in channels
    )
    if not valid_channels:
        raise ValueError("MONITORING_CHANNELS must be a non-empty JSON list of Cloud Monitoring channel resources")
    return {"clamav_source_digest_pinned": True, "notification_channels": channels, "database_disk_autoresize_limit_gb": disk_limit, "otlp_endpoint": otlp}


def validate(values: Mapping[str, str]) -> InputReport:
    validated: dict[str, object] = {}
    validated.update(_identity_inputs(values))
    validated["oidc"] = _oidc_inputs(values)
    validated.update(_delivery_inputs(values))
    return InputReport(validated)


def verify_oidc_discovery(report: InputReport, *, timeout: float = 10.0) -> dict[str, object]:
    oidc = report.values["oidc"]
    assert isinstance(oidc, dict)
    issuer = str(oidc["issuer"])
    discovery_url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    req = Request(discovery_url, headers={"Accept": "application/json", "User-Agent": "korpus-production-preflight/1"})
    context = ssl.create_default_context()
    with urlopen(req, timeout=timeout, context=context) as response:  # noqa: S310 - validated HTTPS endpoint
        if response.status != 200:
            raise ValueError(f"OIDC discovery returned HTTP {response.status}")
        if response.headers.get_content_type() not in {"application/json", "application/jwk-set+json"}:
            raise ValueError("OIDC discovery did not return a JSON content type")
        body = response.read(1_048_577)
        if len(body) > 1_048_576:
            raise ValueError("OIDC discovery document exceeds 1 MiB")
    try:
        doc = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("OIDC discovery response is not valid JSON") from exc
    expected = {
        "issuer": issuer,
        "jwks_uri": oidc["jwks_uri"],
        "authorization_endpoint": oidc["authorization_endpoint"],
        "token_endpoint": oidc["token_endpoint"],
    }
    mismatches = {key: {"expected": value, "observed": doc.get(key)} for key, value in expected.items() if doc.get(key) != value}
    if mismatches:
        raise ValueError(f"OIDC discovery metadata mismatch: {json.dumps(mismatches, sort_keys=True)}")
    return {"status": "PASS", "discovery_url": discovery_url, "matched_fields": sorted(expected)}


def _env() -> dict[str, str]:
    return dict(os.environ)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--probe-oidc", action="store_true")
    parser.add_argument("--oidc-timeout", type=float, default=10.0)
    args = parser.parse_args()
    try:
        report = validate(_env())
        result: dict[str, object] = {"schema_version": 1, "status": "PASS", "inputs": report.values}
        if args.probe_oidc:
            result["oidc_discovery"] = verify_oidc_discovery(report, timeout=args.oidc_timeout)
    except (ValueError, OSError) as exc:
        print(f"production-inputs: {exc}", file=sys.stderr)
        return 2
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
