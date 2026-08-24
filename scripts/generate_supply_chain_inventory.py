#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from release_identity import release_tag
from supply_chain_metadata import (
    DECLARED,
    NOT_INSTALLED,
    PUBLISHER_DECLARED,
    PUBLISHER_METADATA,
    component_license,
    installed_licenses,
    normalize,
    publisher_licenses,
)

ROOT = Path(__file__).resolve().parents[1]
LOCKS = [ROOT / "apps/api/requirements.runtime.lock", ROOT / "apps/api/requirements.dev.lock"]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)")
UNRESOLVED = "UNKNOWN_REQUIRES_EXTERNAL_METADATA_AND_LEGAL_REVIEW"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _python_components() -> dict[tuple[str, str], dict[str, object]]:
    installed = installed_licenses()
    publisher = publisher_licenses()
    components: dict[tuple[str, str], dict[str, object]] = {}
    for lock in LOCKS:
        joined = lock.read_text(encoding="utf-8").replace("\\\n", " ")
        for raw in joined.splitlines():
            line = " ".join(raw.split())
            if not line or line.startswith("#") or line.startswith("-r "):
                continue
            match = PIN.match(line)
            if not match:
                raise ValueError(f"non-exact dependency in {lock.relative_to(ROOT)}: {line}")
            raw_name, version = match.groups()
            name = normalize(raw_name)
            license_expression, status, declaration = component_license(
                name, version, installed, publisher
            )
            key = (name, version)
            component = components.setdefault(
                key,
                {
                    "type": "library", "name": name, "version": version,
                    "purl": f"pkg:pypi/{name}@{version}", "license": license_expression,
                    "license_status": status, "license_evidence": declaration,
                    "installed_in_inventory_environment": name in installed,
                    "artifact_hashes_present": "--hash=" in line, "sources": [],
                },
            )
            component["sources"].append(lock.relative_to(ROOT).as_posix())
    return components


def build_inventory() -> dict[str, object]:
    components = _python_components()
    package = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        for name, version in sorted(package.get(section, {}).items()):
            normalized = str(version).removeprefix("=")
            components[(name, normalized)] = {
                "type": "library", "name": name, "version": normalized,
                "purl": f"pkg:npm/{name}@{normalized}", "license": None,
                "license_status": UNRESOLVED, "license_evidence": None,
                "installed_in_inventory_environment": False,
                "artifact_hashes_present": False, "sources": ["apps/web/package.json"],
            }
    ordered = sorted(components.values(), key=lambda item: (str(item["name"]), str(item["version"])))
    unresolved = [str(item["name"]) for item in ordered if item["license_status"] in {NOT_INSTALLED, UNRESOLVED}]
    missing_env = [str(item["name"]) for item in ordered if not item["installed_in_inventory_environment"]]
    return {
        "schema": "korpus.supply-chain-inventory.v2", "release": release_tag(),
        "status": "COMPLETE_LICENSE_METADATA_NOT_LEGAL_CLEARANCE" if not unresolved else "PARTIAL_LICENSE_METADATA_NOT_LEGAL_CLEARANCE",
        "environment_status": "LOCKED_PACKAGES_PRESENT" if not missing_env else "PARTIAL_LOCAL_ENVIRONMENT",
        "lockfiles": [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)} for path in LOCKS],
        "publisher_metadata": {"path": PUBLISHER_METADATA.relative_to(ROOT).as_posix(), "sha256": sha256(PUBLISHER_METADATA)},
        "components": ordered,
        "limitations": [
            "License fields are publisher/upstream declarations, not legal clearance.",
            "Publisher metadata fallback does not prove that a locked package is installed.",
            "Vulnerability status remains UNKNOWN until OSV or an equivalent live database scanner executes.",
            "Container operating-system packages are covered by the separate CI/container SBOM gate.",
        ],
        "unresolved_license_metadata": unresolved,
        "packages_not_installed_in_inventory_environment": sorted(set(missing_env)),
    }


def main() -> int:
    output = build_inventory()
    target = ROOT / "var/supply-chain-inventory.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    components = output["components"]
    assert isinstance(components, list)
    summary = {
        "status": output["status"], "environment_status": output["environment_status"],
        "components": len(components),
        "licenses_from_installed_metadata": sum(1 for item in components if item["license_status"] == DECLARED),
        "licenses_from_publisher_metadata": sum(1 for item in components if item["license_status"] == PUBLISHER_DECLARED),
        "unresolved_license_metadata": output["unresolved_license_metadata"],
        "packages_not_installed_in_inventory_environment": output["packages_not_installed_in_inventory_environment"],
        "path": str(target.relative_to(ROOT)),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if output["unresolved_license_metadata"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
