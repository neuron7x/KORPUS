#!/usr/bin/env python3
"""Model-check the exact deployed bounded-plasticity policy and emit release evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]
from korpus.application.plasticity_config import load_plasticity_policy  # noqa: E402
from korpus.application.plasticity_model_check import check_grid  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from scripts.release_identity import release_tag  # noqa: E402


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path,
                        default=ROOT / "config/operations/plasticity-policy.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/plasticity-gate.json")
    args = parser.parse_args()
    try:
        policy, policy_sha256 = load_plasticity_policy(args.policy)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        payload = {
            "schema": "korpus.plasticity-model-check.v2", "status": "FAIL",
            "release": release_tag(), "source_tree_sha256": compute_source_digest(ROOT),
            "failures": [f"invalid policy: {exc}"],
        }
        _write(args.out, payload)
        return 1
    result = check_grid(policy)
    failures = list(result["failures"])
    payload = {
        "schema": "korpus.plasticity-model-check.v2", "status": "FAIL" if failures else "PASS",
        "release": release_tag(), "source_tree_sha256": compute_source_digest(ROOT),
        "policy_path": args.policy.relative_to(ROOT).as_posix() if args.policy.is_relative_to(ROOT)
        else str(args.policy), "policy_sha256": policy_sha256, **result,
    }
    _write(args.out, payload)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
