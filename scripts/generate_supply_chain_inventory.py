#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from release_identity import release_tag
ROOT = Path(__file__).resolve().parents[1]
LOCKS = [ROOT / "apps/api/requirements.runtime.lock", ROOT / "apps/api/requirements.dev.lock"]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)")
UNRESOLVED = "UNKNOWN_REQUIRES_EXTERNAL_METADATA_AND_LEGAL_REVIEW"
# Read from the running interpreter's installed distributions, so the answer depends on
# where this is invoked: under the locked venv all 68 resolve, under a bare python3 five
# do not. Silently emitting UNKNOWN for the difference would have made "we could not
# determine the license" and "you ran this in the wrong environment" the same record.
NOT_INSTALLED = "UNRESOLVED_PACKAGE_NOT_INSTALLED_IN_THIS_ENVIRONMENT"
DECLARED = "DECLARED_BY_PACKAGE_METADATA_NOT_LEGAL_CLEARANCE"


def _installed_licenses() -> dict[str, str]:
    """License expressions as the installed distributions declare them.

    Every component read UNKNOWN, which conflated two different states: a license this
    inventory has not looked up, and a license nobody can determine. The metadata is
    right there in the installed distribution, so the first state was self-inflicted.

    What this is not is legal clearance. A declared SPDX expression is the publisher's
    statement about their own package; whether the combination is usable under the
    terms KORPUS is delivered on is a question for a lawyer, and the status string says
    so rather than letting a populated field read as an answer.
    """
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
            # Some packages put their whole license text in the field. A paragraph is
            # not an identifier, and storing it would make the inventory unreadable.
            expression = declared if 0 < len(declared) <= 64 and "\n" not in declared else ""
        if expression:
            found[re.sub(r"[-_.]+", "-", name).casefold()] = expression
    return found


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    licenses = _installed_licenses()
    components: dict[tuple[str, str], dict[str, object]] = {}
    for lock in LOCKS:
        # A hashed requirement spans several physical lines joined by a backslash.
        # Parsing them separately made every `--hash=` line look like a dependency
        # whose name was "--hash=sha256:..." and killed the inventory outright, which
        # is how this file found out that hashes had arrived.
        joined = lock.read_text(encoding="utf-8").replace("\\\n", " ")
        for raw in joined.splitlines():
            line = " ".join(raw.split())
            if not line or line.startswith("#") or line.startswith("-r "):
                continue
            match = PIN.match(line)
            if not match:
                raise SystemExit(f"non-exact dependency in {lock.relative_to(ROOT)}: {line}")
            name, version = match.groups()
            key = (name.casefold().replace("_", "-"), version)
            component = components.setdefault(
                key,
                {
                    "type": "library",
                    "name": key[0],
                    "version": version,
                    "purl": f"pkg:pypi/{key[0]}@{version}",
                    "license": licenses.get(key[0]),
                    "license_status": DECLARED if key[0] in licenses else NOT_INSTALLED,
                    "artifact_hashes_present": "--hash=" in line,
                    "sources": [],
                },
            )
            component["sources"].append(lock.relative_to(ROOT).as_posix())
    package = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        for name, version in sorted(package.get(section, {}).items()):
            normalized = str(version).removeprefix("=")
            components[(name, normalized)] = {
                "type": "library",
                "name": name,
                "version": normalized,
                "purl": f"pkg:npm/{name}@{normalized}",
                # npm metadata is not installed in this environment; the container SBOM
                # gate reads it. Reporting it as unresolved here is the honest state.
                "license": None,
                "license_status": UNRESOLVED,
                "artifact_hashes_present": False,
                "sources": ["apps/web/package.json"],
            }
    output = {
        "schema": "korpus.supply-chain-inventory.v1",
        "release": release_tag(),
        "status": "PARTIAL_LOCAL_INVENTORY_NOT_LICENSE_CLEARANCE",
        "lockfiles": [
            {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)} for path in LOCKS
        ],
        "components": sorted(
            components.values(),
            key=lambda item: (str(item["type"]), str(item["name"]), str(item["version"])),
        ),
        "limitations": [
            (
                "Python licenses are read from installed distribution metadata: they are "
                "the publisher's declaration, not legal clearance for this delivery."
            ),
            "npm licenses remain unresolved here; the container SBOM gate reads them.",
            "Python lock files are exact-version pins but may not contain artifact hashes.",
            (
                "Container operating-system packages are produced by the CI SBOM gate, "
                "not this source inventory."
            ),
        ],
    }
    target = ROOT / "var/supply-chain-inventory.json"
    target.parent.mkdir(exist_ok=True)
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    unresolved = [
        str(item["name"])
        for item in output["components"]
        if item["license_status"] == NOT_INSTALLED
    ]
    summary = {
        "status": output["status"],
        "components": len(output["components"]),
        "licenses_declared": sum(
            1 for item in output["components"] if item["license_status"] == DECLARED
        ),
        "unresolved_because_not_installed": unresolved,
        "path": str(target.relative_to(ROOT)),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # A locked environment resolves every pinned distribution. Anything left is a
    # difference between the lock and the environment, which is a finding.
    return 1 if unresolved else 0

if __name__ == "__main__":
    raise SystemExit(main())
