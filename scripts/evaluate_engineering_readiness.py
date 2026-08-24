#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.engineering_readiness import evaluate_engineering_profile  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", type=Path, default=ROOT / "config/assurance/engineering-readiness-87.v1.json"
    )
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "reports/ENGINEERING_READINESS_87.json")
    args = parser.parse_args()
    source, release = compute_source_digest(ROOT), release_tag()
    result = evaluate_engineering_profile(
        _load(args.profile.resolve()),
        _load(args.evidence.resolve()),
        source_digest=source,
        release=release,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["target_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
