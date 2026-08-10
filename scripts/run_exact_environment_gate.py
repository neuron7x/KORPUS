#!/usr/bin/env python3
from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.production_assurance import gate_payload  # noqa: E402
from release_identity import release_tag  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402

PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)")
LOCKS = (ROOT / "apps/api/requirements.runtime.lock", ROOT / "apps/api/requirements.dev.lock")


def _pins() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in LOCKS:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = PIN.match(line.strip())
            if match:
                result[match.group(1).lower().replace("_", "-")] = match.group(2)
    return result


def main() -> int:
    pins = _pins()
    installed = {dist.metadata["Name"].lower().replace("_", "-"): dist.version for dist in importlib.metadata.distributions() if dist.metadata.get("Name")}
    missing = sorted(name for name in pins if name not in installed)
    mismatched = {name: {"locked": version, "installed": installed.get(name)} for name, version in pins.items() if installed.get(name) not in {None, version}}
    checks = {
        "all_locked_components_installed": not missing,
        "all_versions_exact": not mismatched,
        "python_requirement": sys.version_info >= (3, 12),
        "lock_hashes_present": all("--hash=sha256:" in path.read_text(encoding="utf-8") for path in LOCKS),
    }
    failures = [name for name, ok in checks.items() if not ok]
    result = gate_payload(
        "exact_environment", status="PASS" if not failures else "FAIL",
        source_digest=compute_source_digest(ROOT), release=release_tag(), checks=checks,
        failures=failures, evidence_class="CURRENT_INTERPRETER",
        python=platform.python_version(), implementation=platform.python_implementation(),
        locked_components=len(pins), missing=missing, mismatched=mismatched,
    )
    out = ROOT / "var/production/exact_environment-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
