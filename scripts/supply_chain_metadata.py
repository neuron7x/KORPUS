"""Exact-version dependency publisher metadata for offline supply-chain inventory."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_METADATA = ROOT / "config/supply-chain/publisher-license-metadata.v1.json"
NOT_INSTALLED = "UNRESOLVED_PACKAGE_NOT_INSTALLED_IN_THIS_ENVIRONMENT"
DECLARED = "DECLARED_BY_INSTALLED_PACKAGE_METADATA_NOT_LEGAL_CLEARANCE"
PUBLISHER_DECLARED = "DECLARED_BY_PUBLISHER_METADATA_NOT_LEGAL_CLEARANCE"
ALLOWED_EVIDENCE = frozenset({"PYPI_PUBLISHER_METADATA", "UPSTREAM_SOURCE_LICENSE"})


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def installed_licenses() -> dict[str, str]:
    """Read publisher-declared licenses from the current interpreter."""
    from importlib.metadata import distributions

    found: dict[str, str] = {}
    for distribution in distributions():
        metadata = distribution.metadata
        name = metadata["Name"]
        if not name:
            continue
        expression = metadata.get("License-Expression") or ""
        if not expression:
            classifiers = [
                value.split("::")[-1].strip()
                for value in metadata.get_all("Classifier") or []
                if value.startswith("License ::")
            ]
            expression = " OR ".join(sorted(set(classifiers)))
        if not expression:
            declared = (metadata.get("License") or "").strip()
            expression = declared if 0 < len(declared) <= 64 and "\n" not in declared else ""
        if expression:
            found[normalize(name)] = expression
    return found


def publisher_licenses(
    path: Path = PUBLISHER_METADATA,
) -> dict[tuple[str, str], dict[str, str]]:
    """Load exact-version declarations; ambiguity or weak provenance is fatal."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "korpus.publisher-license-metadata.v1":
        raise ValueError("invalid publisher license metadata schema")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("publisher license metadata records must be a list")
    result: dict[tuple[str, str], dict[str, str]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("publisher license metadata record must be an object")
        name = normalize(str(raw.get("name", "")))
        version = str(raw.get("version", ""))
        license_expression = str(raw.get("license", ""))
        evidence_kind = str(raw.get("evidence_kind", ""))
        source_url = str(raw.get("source_url", ""))
        parsed = urlparse(source_url)
        if (
            not name
            or not version
            or not license_expression
            or evidence_kind not in ALLOWED_EVIDENCE
            or parsed.scheme != "https"
            or not parsed.netloc
        ):
            raise ValueError(f"invalid publisher license metadata record: {raw!r}")
        key = (name, version)
        if key in result:
            raise ValueError(f"duplicate publisher license metadata record: {key}")
        result[key] = {
            "license": license_expression,
            "evidence_kind": evidence_kind,
            "source_url": source_url,
        }
    return result


def component_license(
    name: str,
    version: str,
    installed: dict[str, str],
    publisher: dict[tuple[str, str], dict[str, str]],
) -> tuple[str | None, str, dict[str, str] | None]:
    if name in installed:
        return installed[name], DECLARED, None
    declaration = publisher.get((name, version))
    if declaration is None:
        return None, NOT_INSTALLED, None
    return declaration["license"], PUBLISHER_DECLARED, declaration
