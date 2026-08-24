#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)")
LOCKS = (ROOT / "apps/api/requirements.runtime.lock", ROOT / "apps/api/requirements.dev.lock")


def main() -> int:
    components: dict[tuple[str, str], dict[str, object]] = {}
    for lock in LOCKS:
        scope = "required" if "runtime" in lock.name else "development"
        for line in lock.read_text(encoding="utf-8").splitlines():
            match = PIN.match(line.strip())
            if not match:
                continue
            name, version = match.groups()
            components[(name.lower(), version)] = {
                "type": "library",
                "name": name,
                "version": version,
                "scope": scope,
                "purl": f"pkg:pypi/{name.lower()}@{version}",
            }
    serial_seed = "\n".join(f"{n}=={v}" for n, v in sorted(components))
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "serialNumber": "urn:uuid:" + hashlib.sha256(serial_seed.encode()).hexdigest()[:32],
        "metadata": {"component": {"type": "application", "name": "korpus-api"}},
        "components": [components[key] for key in sorted(components)],
    }
    out = ROOT / "source-sbom.cdx.json"
    out.write_text(json.dumps(bom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"status": "PASS", "components": len(components), "path": str(out.relative_to(ROOT))}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
