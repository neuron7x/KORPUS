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
from korpus.application.exact_environment import exact_environment_state  # noqa: E402
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)")
PYTHON = re.compile(r"^ARG PYTHON_IMAGE=python:(\d+\.\d+\.\d+)-", re.M)
LOCKS = (ROOT / "apps/api/requirements.runtime.lock", ROOT / "apps/api/requirements.dev.lock")
PROFILE = ROOT / "config/assurance/exact-environment-v1.json"


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
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    installed = {
        d.metadata["Name"].lower().replace("_", "-"): d.version
        for d in importlib.metadata.distributions()
        if d.metadata.get("Name")
    }
    match = PYTHON.search((ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8"))
    required = match.group(1) if match else ""
    hashes_complete = all("--hash=sha256:" in path.read_text(encoding="utf-8") for path in LOCKS)
    checks, missing, mismatched, extras = exact_environment_state(
        pins,
        installed,
        python_version=platform.python_version(),
        required_python=required,
        allowed_unmanaged=profile["allowed_unmanaged_distributions"],
        hashes_complete=hashes_complete,
    )
    failures = [name for name, ok in checks.items() if not ok]
    result = gate_payload(
        "exact_environment",
        status="PASS" if not failures else "FAIL",
        source_digest=compute_source_digest(ROOT),
        release=release_tag(),
        checks=checks,
        failures=failures,
        evidence_class="EXACT_CURRENT_INTERPRETER",
        python=platform.python_version(),
        required_python=required,
        implementation=platform.python_implementation(),
        locked_components=len(pins),
        missing=missing,
        mismatched=mismatched,
        unmanaged_distributions=extras,
    )
    out = ROOT / "var/production/exact_environment-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
