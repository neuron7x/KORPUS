#!/usr/bin/env python3
"""Run a gate and retain a coherent red result without treating it as promotion."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        return 2
    completed = subprocess.run(command, check=False)
    try:
        gate = json.loads(args.out.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1
    passed = gate.get("status") == "PASS" and completed.returncode == 0
    failed = gate.get("status") == "FAIL" and completed.returncode == 1
    coherent = gate.get("schema") == "korpus.production-gate.v1" and (passed or failed)
    print(json.dumps({"gate_id": gate.get("gate_id"), "status": gate.get("status"), "coherent": coherent}, indent=2))
    return 0 if coherent else 1


if __name__ == "__main__":
    raise SystemExit(main())
