from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    ".gitlab-ci.yml",
    ".gitlab/CODEOWNERS",
    "AGENTS.md",
    "apps/api/pyproject.toml",
    "apps/api/src/korpus/main.py",
    "apps/web/package.json",
    "packages/contracts/answer.schema.json",
    "docs/architecture/SYSTEM.md",
    "docs/architecture/SYSTEM_V2.md",
    "docs/assurance/FIRST_PRINCIPLES.md",
    "docs/assurance/TEST_STRATEGY.md",
    "docs/assurance/ASSURANCE_CASE.md",
    "docs/research/RESEARCH_PROVENANCE_2026.md",
    "scripts/run_mutation_tests.py",
    "scripts/run_migration_gate.py",
    "scripts/run_research_assurance.py",
    "scripts/snapshot_assurance.py",
    "scripts/wait_for_database.py",
    "docs/architecture/SECURITY.md",
    "evals/datasets/frozen.jsonl",
]

errors: list[str] = []
for path in REQUIRED:
    if not (ROOT / path).is_file():
        errors.append(f"missing required file: {path}")

for schema in (ROOT / "packages/contracts").glob("*.json"):
    try:
        json.loads(schema.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON schema {schema}: {exc}")

for path in ROOT.rglob("*"):
    if path.is_file() and any(part in {".git", "node_modules", ".venv", "dist", "var"} for part in path.parts):
        continue
    if path.is_file() and path.stat().st_size > 5_000_000:
        errors.append(f"repository file exceeds 5 MB: {path.relative_to(ROOT)}")
    if path.is_file() and path.suffix in {".py", ".ts", ".tsx", ".md", ".yml", ".yaml"}:
        text = path.read_text(errors="ignore")
        placeholder = "TODO" + ": implement"
        not_implemented = "raise " + "NotImplementedError"
        if placeholder in text or not_implemented in text:
            errors.append(f"unresolved implementation placeholder: {path.relative_to(ROOT)}")

if errors:
    print("\n".join(errors))
    raise SystemExit(1)
print(f"repository validation passed: {len(list(ROOT.rglob('*')))} paths")
