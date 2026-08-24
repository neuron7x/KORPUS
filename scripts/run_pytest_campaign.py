#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    targets = [str(item) for item in config["pytest_targets"]]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "apps/api/src")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--disable-warnings", *targets],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=int(config.get("timeout_seconds", 300)),
    )
    checks = {
        "campaign_executed": completed.returncode != 5,
        "pytest_passed": completed.returncode == 0,
        "attack_families_declared": bool(config.get("attack_families")),
    }
    failures = [name for name, ok in checks.items() if not ok]
    result = gate_payload(
        str(config["gate_id"]),
        status="PASS" if not failures else "FAIL",
        source_digest=compute_source_digest(ROOT),
        release=release_tag(),
        checks=checks,
        failures=failures,
        evidence_class=str(config.get("evidence_class", "INTERNAL")),
        attack_families=config.get("attack_families", []),
        pytest_targets=targets,
        pytest_exit_code=completed.returncode,
        stdout_tail=completed.stdout[-8000:],
        stderr_tail=completed.stderr[-4000:],
    )
    out = args.out or ROOT / f"var/production/{config['gate_id']}-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
