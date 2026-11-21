from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from uuid import RFC_4122, UUID

import pytest

from scripts.source_security_contract import (
    OUTPUT_MEMBERS,
    expected_tools,
    validate_audit,
    validate_outputs,
)
from scripts.source_security_lock import build_lock_sbom, locked_packages

from .source_security_fixtures import output_bytes, output_values, write_locks


def test_native_reports_and_exact_lock_universe_are_accepted(tmp_path: Path) -> None:
    write_locks(tmp_path)
    assert locked_packages(tmp_path, "dev") == {
        "example-runtime": "1.2.3",
        "example-check": "4.5.6",
    }
    assert build_lock_sbom(tmp_path) == output_values()["lock-sbom.cdx.json"]
    serial = UUID(build_lock_sbom(tmp_path)["serialNumber"])
    assert serial.variant == RFC_4122 and serial.version == 5
    validate_outputs(output_bytes(), tmp_path)
    # Discovery can contain files or ecosystems not modeled by the Python lock.
    values = output_values()
    values["tree-sbom.cdx.json"]["components"].append(
        {"type": "library", "name": "neutral-js", "version": "1.0", "bom-ref": "other-ecosystem"}
    )
    validate_outputs(output_bytes(values), tmp_path)


def test_lock_sbom_uses_cyclonedx_runtime_scopes_and_runtime_precedence(tmp_path: Path) -> None:
    write_locks(tmp_path)
    components = {item["name"]: item for item in build_lock_sbom(tmp_path)["components"]}
    assert components["example-check"]["scope"] == "excluded"
    assert components["example-runtime"]["scope"] == "required"
    assert all(
        item["scope"] in {"required", "optional", "excluded"} for item in components.values()
    )
    dev = tmp_path / "apps/api/requirements.dev.lock"
    dev.write_text(dev.read_text() + (tmp_path / "apps/api/requirements.runtime.lock").read_text())
    components = {item["name"]: item for item in build_lock_sbom(tmp_path)["components"]}
    assert components["example-runtime"]["scope"] == "required"


@pytest.mark.parametrize("member", OUTPUT_MEMBERS)
def test_every_native_member_is_required(tmp_path: Path, member: str) -> None:
    write_locks(tmp_path)
    members = output_bytes()
    del members[member]
    with pytest.raises(ValueError, match="incomplete"):
        validate_outputs(members, tmp_path)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"dependencies":[],"dependencies":[]}',
        b'{"bad":NaN}',
        b'{"bad":Infinity}',
        b'{"bad":1e999}',
        b"\xff",
        b"{} trailing",
    ],
)
def test_ambiguous_or_nonfinite_json_is_refused(tmp_path: Path, raw: bytes) -> None:
    write_locks(tmp_path)
    members = output_bytes()
    members["pip-audit-runtime.json"] = raw
    with pytest.raises(ValueError):
        validate_outputs(members, tmp_path)


@pytest.mark.parametrize("scope", ["runtime", "dev"])
@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "wrong-version", "duplicate", "skipped", "vulnerable", "fixed"]
)
def test_audit_census_and_findings_are_not_replaceable_by_exit_zero(
    tmp_path: Path, scope: str, mutation: str
) -> None:
    write_locks(tmp_path)
    values = output_values()
    report = values[f"pip-audit-{scope}.json"]
    first = report["dependencies"][0]
    if mutation == "missing":
        report["dependencies"].pop(0)
    elif mutation == "extra":
        report["dependencies"].append({"name": "foreign", "version": "9", "vulns": []})
    elif mutation == "wrong-version":
        first["version"] = "9"
    elif mutation == "duplicate":
        report["dependencies"].append({**first, "name": "Example_Runtime"})
    elif mutation == "skipped":
        first["skip_reason"] = "package was not audited"
    elif mutation == "vulnerable":
        first["vulns"] = [{"id": "CVE-neutral", "fix_versions": ["9"]}]
    else:
        report["fixes"] = [{"name": "example-runtime", "new_version": "9"}]
    with pytest.raises(ValueError):
        validate_outputs(output_bytes(values), tmp_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "failure",
        "boolean-failure",
        "empty",
        "no-summary",
        "count",
        "wrong-tool",
        "wrong-source",
        "wrong-class",
        "wrong-time",
        "secrets",
    ],
)
def test_trivy_requires_actual_passing_configuration_checks(tmp_path: Path, mutation: str) -> None:
    write_locks(tmp_path)
    values = output_values()
    report = values["trivy.json"]
    result = report["Results"][0]
    if mutation == "failure":
        result["Misconfigurations"][0]["Status"] = "FAIL"
    elif mutation == "boolean-failure":
        result["MisconfSummary"]["Failures"] = False
    elif mutation == "empty":
        report["Results"] = []
    elif mutation == "no-summary":
        result.pop("MisconfSummary")
    elif mutation == "count":
        result["MisconfSummary"]["Successes"] = 2
    elif mutation == "wrong-tool":
        report["Trivy"]["Version"] = "0.1.0"
    elif mutation == "wrong-source":
        report["ArtifactName"] = "/another-source"
    elif mutation == "wrong-class":
        result["Class"] = "os-pkgs"
    elif mutation == "wrong-time":
        report["CreatedAt"] = "2026-11-19T00:00:00"
    else:
        result["Secrets"] = [{"RuleID": "neutral"}]
    with pytest.raises(ValueError):
        validate_outputs(output_bytes(values), tmp_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "foreign-tool",
        "foreign-source",
        "boolean-version",
        "duplicate-component",
        "missing-name",
        "bad-serial",
        "bad-time",
    ],
)
def test_tree_sbom_must_be_native_bound_discovery(tmp_path: Path, mutation: str) -> None:
    write_locks(tmp_path)
    values = output_values()
    report = values["tree-sbom.cdx.json"]
    if mutation == "empty":
        report["components"] = []
    elif mutation == "foreign-tool":
        report["metadata"]["tools"]["components"][0]["version"] = "1.0.0"
    elif mutation == "foreign-source":
        report["metadata"]["component"]["name"] = "/foreign"
    elif mutation == "boolean-version":
        report["version"] = True
    elif mutation == "duplicate-component":
        report["components"].append(copy.deepcopy(report["components"][0]))
    elif mutation == "missing-name":
        report["components"][0].pop("name")
    elif mutation == "bad-serial":
        report["serialNumber"] = "invented"
    else:
        report["metadata"]["timestamp"] = "not-a-time"
    with pytest.raises(ValueError):
        validate_outputs(output_bytes(values), tmp_path)


@pytest.mark.parametrize("mutation", ["missing", "foreign", "wrong-scope", "boolean-version"])
def test_lock_sbom_is_exact_not_an_arbitrary_cyclonedx_document(
    tmp_path: Path, mutation: str
) -> None:
    write_locks(tmp_path)
    values = output_values()
    report = values["lock-sbom.cdx.json"]
    if mutation == "missing":
        report["components"].pop()
    elif mutation == "foreign":
        report["components"][0]["version"] = "999"
    elif mutation == "wrong-scope":
        report["components"][0]["scope"] = "required"
    else:
        report["version"] = True
    with pytest.raises(ValueError, match="lock SBOM"):
        validate_outputs(output_bytes(values), tmp_path)


@pytest.mark.parametrize("value", [None, {}, [{"RuleID": "neutral", "Secret": "REDACTED"}], "PASS"])
def test_gitleaks_requires_native_empty_findings(tmp_path: Path, value: object) -> None:
    write_locks(tmp_path)
    members = output_bytes()
    members["gitleaks.json"] = json.dumps(value).encode()
    with pytest.raises(ValueError, match="Gitleaks"):
        validate_outputs(members, tmp_path)


def test_tool_lock_identity_uses_actual_bytes(tmp_path: Path) -> None:
    write_locks(tmp_path)
    lock = tmp_path / "apps/api/requirements.scanners.lock"
    before = expected_tools(tmp_path)
    assert before["pip-audit"]["lock"]["sha256"] == hashlib.sha256(lock.read_bytes()).hexdigest()
    assert all("@sha256:" in before[name]["image"] for name in ("gitleaks", "trivy", "syft"))
    lock.write_bytes(lock.read_bytes() + b"# changed toolchain\n")
    assert expected_tools(tmp_path) != before


def test_isolated_scanner_toolchain_requires_its_own_complete_clean_audit(tmp_path: Path) -> None:
    write_locks(tmp_path)
    report = {
        "dependencies": [{"name": "pip-audit", "version": "2.10.1", "vulns": []}],
        "fixes": [],
    }
    validate_audit(report, tmp_path, "scanners")
    with pytest.raises(ValueError, match="census"):
        validate_audit(output_values()["pip-audit-dev.json"], tmp_path, "scanners")
    report["dependencies"][0]["vulns"] = [{"id": "CVE-neutral"}]
    with pytest.raises(ValueError, match="vulnerability"):
        validate_audit(report, tmp_path, "scanners")


def test_duplicate_key_with_a_valid_last_value_is_not_laundered(tmp_path: Path) -> None:
    write_locks(tmp_path)
    members = output_bytes()
    raw = members["pip-audit-runtime.json"]
    members["pip-audit-runtime.json"] = raw.replace(
        b'"dependencies":', b'"dependencies": [], "dependencies":', 1
    )
    with pytest.raises(ValueError, match="duplicate"):
        validate_outputs(members, tmp_path)


@pytest.mark.parametrize("nonfinite", [b"NaN", b"Infinity", b"1e999"])
def test_nonfinite_extension_cannot_hide_in_an_otherwise_valid_report(
    tmp_path: Path, nonfinite: bytes
) -> None:
    write_locks(tmp_path)
    members = output_bytes()
    members["tree-sbom.cdx.json"] = (
        b'{"extension":' + nonfinite + b"," + members["tree-sbom.cdx.json"][1:]
    )
    with pytest.raises(ValueError, match="non-finite"):
        validate_outputs(members, tmp_path)


@pytest.mark.parametrize(
    "extra",
    [
        "-r unknown.lock\n",
        "unresolved>=1\n",
        "example-runtime==1.2.3 \\\n    --hash=sha256:" + "a" * 64 + "\n",
    ],
)
def test_unknown_or_duplicate_lock_requirements_cannot_shrink_census(
    tmp_path: Path, extra: str
) -> None:
    write_locks(tmp_path)
    path = tmp_path / "apps/api/requirements.runtime.lock"
    path.write_text(path.read_text() + extra)
    with pytest.raises(ValueError):
        locked_packages(tmp_path, "runtime")
