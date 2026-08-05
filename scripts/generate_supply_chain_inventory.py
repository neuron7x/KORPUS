#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKS = [ROOT / "apps/api/requirements.runtime.lock", ROOT / "apps/api/requirements.dev.lock"]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
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
                    "license_status": "UNKNOWN_REQUIRES_EXTERNAL_METADATA_AND_LEGAL_REVIEW",
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
                "license_status": "UNKNOWN_REQUIRES_EXTERNAL_METADATA_AND_LEGAL_REVIEW",
                "artifact_hashes_present": False,
                "sources": ["apps/web/package.json"],
            }
    output = {
        "schema": "korpus.supply-chain-inventory.v1",
        "release": "v5.0.0",
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
                "Package licenses are not asserted without authoritative package "
                "metadata and legal review."
            ),
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
    summary = {
        "status": output["status"],
        "components": len(output["components"]),
        "path": str(target.relative_to(ROOT)),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
