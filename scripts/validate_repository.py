from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md",
    "docs/product/SPECIFICATION.md",
    "docs/architecture/SYSTEM.md",
    "docs/architecture/SECURITY.md",
    "docs/protocols/INGESTION.md",
    "docs/governance/RISK_REGISTER.md",
    "packages/contracts/answer.schema.json",
    "agents/prompts/researcher.md",
]


def main() -> None:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    if missing:
        raise SystemExit(f"Missing required repository artifacts: {missing}")
    for schema in (ROOT / "packages/contracts").glob("*.json"):
        json.loads(schema.read_text(encoding="utf-8"))
    print(f"repository validation passed: {len(REQUIRED)} required artifacts")


if __name__ == "__main__":
    main()

