"""Native source scanner semantics shared by producer and authenticated importer.

These checks establish output meaning inside a separately verified execution
boundary. A self-consistent JSON receipt alone is not external attestation.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from scripts.source_security_lock import build_lock_sbom, canonical_name, locked_packages
from scripts.source_security_native import OUTPUT_MEMBERS, validate_gitleaks_log

SCHEMA = "korpus.source-security-execution.v2"
SCANNER_LOCK = "apps/api/requirements.scanners.lock"
PIP_AUDIT_VERSION = "2.10.1"
IMAGES = {
    "gitleaks": "zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f",
    "trivy": "aquasec/trivy:0.70.0@sha256:be1190afcb28352bfddc4ddeb71470835d16462af68d310f9f4bca710961a41e",
    "syft": "anchore/syft:v1.44.0-debug@sha256:6dd8fb28e1b799e7cadaff6be2ec6d555757c4eeec0c0e48162f20b042ffa1ff",
}
EXECUTION_NAMES = ("gitleaks", "pip-audit:runtime", "pip-audit:dev", "trivy", "syft")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(raw: str) -> Any:
    raise ValueError(f"non-finite JSON number: {raw}")


def _float(raw: str) -> float:
    value = float(raw)
    require(math.isfinite(value), "non-finite JSON number")
    return value


def strict_json(raw: bytes) -> Any:
    try:
        return json.loads(
            raw, object_pairs_hook=_pairs, parse_constant=_nonfinite, parse_float=_float
        )
    except RecursionError as error:
        raise ValueError("JSON nesting exceeds the parser limit") from error


def expected_tools(root: Path) -> dict[str, Any]:
    return {
        **{name: {"image": image} for name, image in IMAGES.items()},
        "pip-audit": {
            "version": PIP_AUDIT_VERSION,
            "lock": {
                "path": SCANNER_LOCK,
                "sha256": hashlib.sha256((root / SCANNER_LOCK).read_bytes()).hexdigest(),
            },
        },
    }


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label}: expected an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label}: expected a list")
    return value


def _counter(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("scanner count is not a nonnegative integer")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("scanner identity is not a nonempty string")
    return value


def _timestamp(value: Any) -> None:
    require(isinstance(value, str), "missing scanner timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "scanner timestamp lacks a timezone")


def validate_audit(value: Any, root: Path, kind: str) -> None:
    report = _object(value, "pip-audit")
    require(set(report) == {"dependencies", "fixes"}, "unexpected pip-audit output fields")
    require(report["fixes"] == [], "pip-audit cannot repair dependencies in an evidence run")
    dependencies = report["dependencies"]
    require(isinstance(dependencies, list), "missing audited dependencies")
    actual: dict[str, str] = {}
    for item in dependencies:
        dependency = _object(item, "pip-audit dependency")
        require(
            set(dependency) == {"name", "version", "vulns"},
            "skipped or malformed audited dependency",
        )
        require(
            isinstance(dependency["name"], str) and isinstance(dependency["version"], str),
            "invalid audited package identity",
        )
        name = canonical_name(dependency["name"])
        require(
            name not in actual and dependency["vulns"] == [],
            "duplicate dependency or known vulnerability",
        )
        actual[name] = dependency["version"]
    require(actual == locked_packages(root, kind), f"pip-audit {kind} lock census differs")


def _trivy_result(item: Any) -> int:
    result = _object(item, "Trivy result")
    _text(result.get("Target"))
    _text(result.get("Type"))
    require(
        result.get("Class") == "config" and bool(result.get("Target")),
        "unexpected Trivy scan scope",
    )
    require(
        not result.get("Vulnerabilities") and not result.get("Secrets"), "Trivy findings present"
    )
    findings = result.get("Misconfigurations", [])
    require(isinstance(findings, list), "invalid Trivy findings")
    summary = result.get("MisconfSummary")
    if summary is None:
        require(findings == [], "Trivy summary omitted findings")
        return 0
    summary = _object(summary, "Trivy summary")
    require(_counter(summary.get("Failures")) == 0, "Trivy failures present")
    successes = _counter(summary.get("Successes"))
    require(
        type(successes) is int and successes == len(findings), "Trivy checked-rule census differs"
    )
    for item in findings:
        finding = _object(item, "Trivy finding")
        require(
            finding.get("Status") == "PASS" and finding.get("Severity") in {"HIGH", "CRITICAL"},
            "nonpassing Trivy check",
        )
    return successes


def _trivy(value: Any) -> None:
    report = _object(value, "Trivy")
    require(
        type(report.get("SchemaVersion")) is int and report["SchemaVersion"] == 2,
        "unsupported Trivy schema",
    )
    tool = _object(report.get("Trivy"), "Trivy tool")
    require(tool.get("Version") == "0.70.0", "wrong Trivy version")
    require(
        report.get("ArtifactName") == "/source" and report.get("ArtifactType") == "filesystem",
        "wrong Trivy source",
    )
    _timestamp(report.get("CreatedAt"))
    results = _list(report.get("Results"), "Trivy results")
    require(bool(results), "Trivy did not report checked configurations")
    require(
        sum(_trivy_result(item) for item in results) > 0, "Trivy checked no HIGH/CRITICAL rules"
    )


def _tree_components(value: Any) -> None:
    components = _list(value, "Syft components")
    require(bool(components), "empty tree SBOM inventory")
    references: set[str] = set()
    for item in components:
        entry = _object(item, "Syft component")
        reference = _text(entry.get("bom-ref"))
        require(
            isinstance(reference, str) and bool(reference) and reference not in references,
            "duplicate or missing tree SBOM component reference",
        )
        require(
            isinstance(entry.get("name"), str)
            and bool(entry["name"])
            and entry.get("type")
            in {
                "application",
                "framework",
                "library",
                "container",
                "platform",
                "operating-system",
                "device",
                "device-driver",
                "firmware",
                "file",
                "machine-learning-model",
                "data",
                "cryptographic-asset",
            },
            "invalid tree SBOM component",
        )
        references.add(reference)


def _tree_sbom(value: Any) -> None:
    report = _object(value, "Syft")
    require(
        report.get("bomFormat") == "CycloneDX" and report.get("specVersion") == "1.6",
        "unsupported tree SBOM format",
    )
    require(
        type(report.get("version")) is int and report["version"] == 1, "wrong tree SBOM version"
    )
    require(isinstance(report.get("serialNumber"), str), "missing tree SBOM serial number")
    require(
        UUID(report["serialNumber"]).urn == report["serialNumber"],
        "invalid tree SBOM serial number",
    )
    metadata = _object(report.get("metadata"), "Syft metadata")
    _timestamp(metadata.get("timestamp"))
    tools = _object(metadata.get("tools"), "Syft tools")
    require(
        tools.get("components")
        == [{"type": "application", "author": "anchore", "name": "syft", "version": "1.44.0"}],
        "wrong tree SBOM tool",
    )
    component = _object(metadata.get("component"), "Syft source")
    require(
        component.get("type") == "file" and component.get("name") == "/source", "wrong Syft source"
    )
    _tree_components(report.get("components"))
    require(not report.get("vulnerabilities"), "tree SBOM reports vulnerabilities")


def validate_outputs(members: Mapping[str, bytes], root: Path) -> None:
    require(
        set(members) == set(OUTPUT_MEMBERS), "source-security outputs are incomplete or ambiguous"
    )
    validate_gitleaks_log(members["gitleaks.log"])
    parsed = {name: strict_json(raw) for name, raw in members.items() if name != "gitleaks.log"}
    require(parsed["gitleaks.json"] == [], "Gitleaks reports findings or invalid output")
    validate_audit(parsed["pip-audit-runtime.json"], root, "runtime")
    validate_audit(parsed["pip-audit-dev.json"], root, "dev")
    require(
        json.dumps(parsed["lock-sbom.cdx.json"], sort_keys=True)
        == json.dumps(build_lock_sbom(root), sort_keys=True),
        "lock SBOM is not the exact dependency universe",
    )
    _trivy(parsed["trivy.json"])
    _tree_sbom(parsed["tree-sbom.cdx.json"])
