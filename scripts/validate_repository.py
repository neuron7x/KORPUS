from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_VERSION = "5.0.0"
REQUIRED = [
    ".dockerignore",
    ".gitlab-ci.yml",
    ".gitlab/CODEOWNERS",
    "AGENTS.md",
    "README.md",
    "FINAL_PACKAGE_CONTENTS.md",
    "DISTRIBUTION_CONTENTS.md",
    "GITLAB_IMPORT.md",
    "VERIFICATION_REPORT_V5.md",
    "SECURITY.md",
    "docker-compose.yml",
    "pytest.ini",
    "apps/api/pyproject.toml",
    "apps/api/requirements.runtime.lock",
    "apps/api/requirements.dev.lock",
    "apps/api/src/korpus/main.py",
    "apps/api/src/korpus/security/browser_oidc.py",
    "apps/api/src/korpus/security/corpus_governance.py",
    "apps/api/src/korpus/security/entitlements.py",
    "apps/api/src/korpus/security/reviewers.py",
    "apps/api/src/korpus/security/scanning.py",
    "apps/api/src/korpus/security/source_authenticity.py",
    "apps/api/src/korpus/infrastructure/ingestion_jobs.py",
    "apps/api/src/korpus/infrastructure/parser_worker.py",
    "apps/web/package.json",
    "packages/contracts/answer.schema.json",
    "contracts/openapi.json",
    "deploy/kubernetes/base/kustomization.yaml",
    "deploy/kubernetes/overlays/production/kustomization.yaml",
    "evals/EVALUATION_PROTOCOL.md",
    "evals/datasets/frozen.jsonl",
    "infra/minio/korpus-app-policy.json",
    "docs/architecture/SYSTEM_V5.md",
    "docs/architecture/SECURITY.md",
    "docs/assurance/ASSURANCE_CASE.md",
    "docs/assurance/FIRST_PRINCIPLES.md",
    "docs/assurance/TEST_STRATEGY.md",
    "docs/audit/source/KORPUS_v4_FINDINGS_REGISTER_2026-08-01.json",
    "docs/audit/source/KORPUS_v4_EXTENDED_ASSURANCE_ACT_2026-08-01.pdf",
    "docs/audit/source/KORPUS_v4_EXTENDED_ASSURANCE_ACT_2026-08-01.docx",
    "docs/audit/source/KORPUS_v4_EXTENDED_ASSURANCE_ACT_2026-08-01.md",
    "docs/audit/source/KORPUS_v4_EXTENDED_AUDIT_PACKAGE_2026-08-01.zip",
    "docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json",
    "docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.csv",
    "docs/audit/closure/KORPUS_v5_CLOSURE_SUMMARY.md",
    "docs/audit/closure/KORPUS_v5_REMAINING_DEBT.json",
    "docs/audit/closure/KORPUS_v5_REMAINING_DEBT.csv",
    "docs/governance/AI_SYSTEM_CARD_V5.md",
    "docs/governance/AUTHORIZATION_PACKAGE_V5.md",
    "docs/governance/DATA_HANDLING_STANDARD_V5.md",
    "docs/operations/SLO_AND_RELEASE_POLICY_V5.md",
    "docs/operations/TEVV_PLAN_V5.md",
    "docs/operations/TECHNICAL_DEBT_V5.md",
    "docs/security/KEY_AND_BREAK_GLASS_V5.md",
    "docs/security/THREAT_MODEL_V5.md",
    "scripts/assemble_assurance.py",
    "scripts/backup_crypto.py",
    "scripts/backup_manifest.py",
    "scripts/backup_postgres.sh",
    "scripts/build_audit_closure.py",
    "scripts/build_system_manifest.py",
    "scripts/generate_desired_state.py",
    "scripts/generate_supply_chain_inventory.py",
    "config/operations/desired-state-v5.json",
    "config/operations/reference-v5.json",
    "scripts/openapi_contract.py",
    "scripts/package_repository.sh",
    "scripts/restore_postgres.sh",
    "scripts/run_evals.py",
    "scripts/run_migration_gate.py",
    "scripts/run_mutation_shards.sh",
    "scripts/run_mutation_tests.py",
    "scripts/run_operational_gate.py",
    "scripts/run_research_assurance.py",
    "scripts/run_scale_probe.py",
    "scripts/snapshot_assurance.py",
    "scripts/source_digest.py",
    "scripts/validate_infrastructure.py",
    "scripts/validate_kubernetes.py",
    "scripts/verify_postgres_restore.py",
    "scripts/verify_release_evidence.py",
]
MIGRATIONS = [
    "0001_initial.py",
    "0002_database_defense_and_vectors.py",
    "0003_infrastructure_hardening.py",
    "0004_compartmented_authorization.py",
    "0005_durable_ingestion_jobs.py",
    "0006_source_authenticity.py",
    "0007_near_duplicate_governance.py",
    "0008_extraction_quality_governance.py",
    "0009_reviewer_credentials.py",
]
SKIP_PARTS = {".git", "node_modules", ".venv", "dist", "var", ".pytest_cache", "__pycache__"}


def load_json(path: Path, errors: list[str]) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid JSON {path.relative_to(ROOT)}: {exc}")
        return None


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required file: {relative}")
    migration_root = ROOT / "apps/api/migrations/versions"
    for filename in MIGRATIONS:
        if not (migration_root / filename).is_file():
            errors.append(f"missing migration: {filename}")

    for schema in (ROOT / "packages/contracts").glob("*.json"):
        load_json(schema, errors)
    load_json(ROOT / "contracts/openapi.json", errors)

    closure = load_json(ROOT / "docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json", errors)
    if isinstance(closure, dict):
        findings = closure.get("findings")
        counts = closure.get("counts")
        if closure.get("target_release") != "v5.0.0":
            errors.append("audit closure target_release must be v5.0.0")
        if not isinstance(findings, list) or len(findings) != 99:
            errors.append("audit closure must classify exactly 99 source findings")
        if not isinstance(counts, dict) or sum(int(value) for value in counts.values()) != 99:
            errors.append("audit closure status counts must sum to 99")

    pyproject_path = ROOT / "apps/api/pyproject.toml"
    if pyproject_path.is_file():
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        if pyproject.get("project", {}).get("version") != RELEASE_VERSION:
            errors.append(f"API project version must be {RELEASE_VERSION}")
    package_path = ROOT / "apps/web/package.json"
    package = load_json(package_path, errors) if package_path.is_file() else None
    if isinstance(package, dict) and package.get("version") != RELEASE_VERSION:
        errors.append(f"web package version must be {RELEASE_VERSION}")
    init_text = (ROOT / "apps/api/src/korpus/__init__.py").read_text(encoding="utf-8")
    if f'__version__ = "{RELEASE_VERSION}"' not in init_text:
        errors.append(f"runtime __version__ must be {RELEASE_VERSION}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").is_file() else ""
    if not readme.startswith("# KORPUS v5.0.0"):
        errors.append("README release header must be KORPUS v5.0.0")

    placeholder_patterns = (
        re.compile(r"TODO:\s*implement", re.I),
        re.compile(r"raise\s+NotImplementedError"),
    )
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        relative = path.relative_to(ROOT)
        if path.stat().st_size > 5_000_000:
            errors.append(f"repository file exceeds 5 MB: {relative}")
        if path.suffix in {".py", ".ts", ".tsx", ".js", ".md", ".yml", ".yaml", ".sh"}:
            text = path.read_text(errors="ignore")
            if any(pattern.search(text) for pattern in placeholder_patterns):
                errors.append(f"unresolved implementation placeholder: {relative}")
        if relative.as_posix().startswith("infra/secrets/") and path.suffix == ".txt":
            errors.append(f"plaintext runtime secret tracked in repository: {relative}")

    if errors:
        print("\n".join(errors))
        return 1
    path_count = sum(1 for _ in ROOT.rglob("*"))
    print(f"repository validation passed: {path_count} paths, 99/99 audit findings classified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
