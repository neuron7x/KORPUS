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
    # The instruments are artifacts too: if the eval runner or the mutation catalogue
    # disappears, the pipeline stays green while measuring nothing.
    "scripts/run_evals.py",
    "evals/datasets/seed.jsonl",
    "evals/datasets/manifest.json",
    "tools/mutation.py",
    "tools/mutants.json",
    "tools/mutation_baseline.json",
    "scripts/ingest.py",
    "scripts/calibrate.py",
    "config/calibration.json",
]


def check_schemas() -> None:
    for schema in (ROOT / "packages/contracts").glob("*.json"):
        json.loads(schema.read_text(encoding="utf-8"))


def check_eval_dataset() -> None:
    """A dataset that parses but holds nothing is the quiet failure mode."""
    dataset = ROOT / "evals/datasets/seed.jsonl"
    manifest = json.loads((ROOT / "evals/datasets/manifest.json").read_text(encoding="utf-8"))
    cases = [line for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cases:
        raise SystemExit("eval dataset is empty — a run over zero cases cannot pass")
    parsed = [json.loads(line) for line in cases]
    for number, case in enumerate(parsed, 1):
        for field in ("id", "query", "expected_status", "rationale"):
            if field not in case:
                raise SystemExit(f"evals/datasets/seed.jsonl:{number}: missing '{field}'")
    floor = manifest.get("seed.jsonl", {})
    if len(parsed) < int(floor.get("cases", 0)):
        raise SystemExit(
            f"eval dataset shrank to {len(parsed)} cases, manifest records {floor['cases']}"
        )
    covered = {case["expected_status"] for case in parsed}
    missing = set(floor.get("statuses", [])) - covered
    if missing:
        raise SystemExit(f"eval dataset no longer covers: {sorted(missing)}")


def check_mutation_catalogue() -> None:
    catalogue = json.loads((ROOT / "tools/mutants.json").read_text(encoding="utf-8"))
    baseline = json.loads((ROOT / "tools/mutation_baseline.json").read_text(encoding="utf-8"))
    size = len(catalogue["mutants"])
    recorded = int(baseline.get("catalogue_size", 0))
    if size < recorded:
        raise SystemExit(f"mutation catalogue shrank: {size} < recorded {recorded}")
    ids = [mutant["id"] for mutant in catalogue["mutants"]]
    if len(set(ids)) != len(ids):
        raise SystemExit("duplicate mutant ids in tools/mutants.json")


def main() -> None:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    if missing:
        raise SystemExit(f"Missing required repository artifacts: {missing}")
    check_schemas()
    check_eval_dataset()
    check_mutation_catalogue()
    print(f"repository validation passed: {len(REQUIRED)} required artifacts")


if __name__ == "__main__":
    main()
