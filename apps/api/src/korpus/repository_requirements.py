"""What the repository itself must contain and must not, as named requirements.

The second of the three inline validators. `validate_repository.main` measured 33 and
held four different kinds of check in one loop: files that must exist, versions that
must agree across four places, an audit closure that must classify exactly ninety-nine
findings, and a filesystem walk looking for oversized files, unresolved placeholders
and plaintext secrets.

The walk is done once, in the context, and three requirements read its result. Doing it
per-requirement would have traversed the tree three times to answer three questions
about the same traversal.

Required files and migrations are expanded into one requirement each, so a missing
`SECURITY.md` and a missing migration are separate findings with separate ids rather
than two lines in a list — which is what makes either citable.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from korpus.application.requirements import Requirement
from korpus.release import RELEASE_VERSION


class _Everything(frozenset[str]):
    """Contains every path. Used when git cannot say which secrets are tracked."""

    def __contains__(self, item: object) -> bool:
        return True


_EVERYTHING = _Everything()

MAX_FILE_BYTES = 5_000_000
EXPECTED_FINDINGS = 99

PLACEHOLDER_PATTERNS = (
    re.compile(r"TODO:\s*implement", re.I),
    re.compile(r"raise\s+NotImplementedError"),
)
SCANNED_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".js", ".md", ".yml", ".yaml", ".sh"})

# Everything .gitignore excludes as a directory, plus .git itself. The walk asks "what
# is in the repository" while walking the *filesystem*, so anything a tool drops in the
# checkout counts as repository content. In CI that is PIP_CACHE_DIR: the first pipeline
# where this job had a locked environment reported five pip wheels as oversized files.
# Kept in step with .gitignore by test_gate_parity.py.
SKIP_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "htmlcov",
        "node_modules",
        ".next",
        "dist",
        "build",
        "var",
    }
)

REQUIRED_FILES = (
    ".dockerignore",
    ".gitlab-ci.yml",
    ".gitlab/CODEOWNERS",
    ".github/dependabot.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/engineering-change.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/assurance.yml",
    ".github/workflows/dependency-review.yml",
    ".github/workflows/release.yml",
    "AGENTS.md",
    "README.md",
    "FINAL_PACKAGE_CONTENTS.md",
    "DISTRIBUTION_CONTENTS.md",
    "GITLAB_IMPORT.md",
    "GITHUB_IMPORT.md",
    "VERIFICATION_REPORT.md",
    "SECURITY.md",
    "docker-compose.yml",
    "pytest.ini",
    "apps/api/pyproject.toml",
    "apps/api/src/korpus/release.json",
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
    "docs/architecture/SYSTEM.md",
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
    "scripts/validate_github_actions.py",
    "scripts/generate_supply_chain_inventory.py",
    "config/operations/desired-state.json",
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
)

REQUIRED_MIGRATIONS = (
    "0001_initial.py",
    "0002_database_defense_and_vectors.py",
    "0003_infrastructure_hardening.py",
    "0004_compartmented_authorization.py",
    "0005_durable_ingestion_jobs.py",
    "0006_source_authenticity.py",
    "0007_near_duplicate_governance.py",
    "0008_extraction_quality_governance.py",
    "0009_reviewer_credentials.py",
)


@dataclass
class RepositoryContext:
    """One filesystem walk, three questions asked of its result."""

    root: Path
    oversized: list[str] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)
    tracked_secrets: list[str] = field(default_factory=list)
    invalid_json: list[str] = field(default_factory=list)
    closure: dict[str, Any] = field(default_factory=dict)
    pyproject: dict[str, Any] = field(default_factory=dict)
    package: dict[str, Any] = field(default_factory=dict)
    release_identity: dict[str, Any] = field(default_factory=dict)
    init_text: str = ""
    readme: str = ""
    path_count: int = 0

    def exists(self, relative: str) -> bool:
        return (self.root / relative).is_file()


def load_context(root: Path) -> RepositoryContext:
    context = RepositoryContext(root=root)
    tracked = _git_tracked_secrets(root)
    # None means git could not answer — a packaged distribution, no repository. Falling
    # back to "every secret file present is tracked" is the conservative direction: a
    # shipped credential must fail, and outside a repository nothing can tell a shipped
    # one from an ignored one.
    git_tracked = tracked if tracked is not None else _EVERYTHING

    def read_json(relative: str) -> Any:
        path = root / relative
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            context.invalid_json.append(f"{relative}: {error}")
            return None

    for schema in sorted((root / "packages/contracts").glob("*.json")):
        read_json(str(schema.relative_to(root)))
    read_json("contracts/openapi.json")
    closure = read_json("docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json")
    context.closure = closure if isinstance(closure, dict) else {}

    pyproject_path = root / "apps/api/pyproject.toml"
    if pyproject_path.is_file():
        context.pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    package = read_json("apps/web/package.json")
    context.package = package if isinstance(package, dict) else {}
    release_identity = read_json("apps/api/src/korpus/release.json")
    context.release_identity = release_identity if isinstance(release_identity, dict) else {}
    init_path = root / "apps/api/src/korpus/__init__.py"
    context.init_text = init_path.read_text(encoding="utf-8") if init_path.is_file() else ""
    readme_path = root / "README.md"
    context.readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""

    _scan_tree(context, root, git_tracked)
    return context


def _scan_tree(context: RepositoryContext, root: Path, git_tracked: object) -> None:
    for path in root.rglob("*"):
        context.path_count += 1
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        relative = path.relative_to(root).as_posix()
        if path.stat().st_size > MAX_FILE_BYTES:
            context.oversized.append(relative)
        if path.suffix in SCANNED_SUFFIXES:
            text = path.read_text(errors="ignore")
            if any(pattern.search(text) for pattern in PLACEHOLDER_PATTERNS):
                context.placeholders.append(relative)
        if relative.startswith("infra/secrets/") and path.suffix == ".txt" and relative in git_tracked:
            context.tracked_secrets.append(relative)


def _git_tracked_secrets(root: Path) -> frozenset[str] | None:
    """Paths under infra/secrets that git is actually tracking.

    The requirement is named `tracked_secrets` and measured presence on disk. Those are
    different things, and the difference is this repository's own documented workflow:
    `make infra-secrets` writes eight key files there — `infra/secrets/.gitignore` says
    `*.txt`, so git never sees them — and running it made `make validate` fail on files
    git was explicitly ignoring. A developer following the README broke the validator by
    following the README (found 2026-08-06 while starting the local stack).

    Returns None when git cannot answer: a packaged distribution has no repository, and
    there the conservative reading — any secret file present is a finding — is the right
    one, because nothing else can distinguish "ignored" from "shipped".
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z", "--", "infra/secrets"],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return frozenset(
        entry.decode("utf-8", "replace")
        for entry in completed.stdout.split(b"\0")
        if entry
    )


def _requirement(
    identifier: str, statement: str, holds: Any, rationale: str = ""
) -> Requirement:
    return Requirement(
        id=identifier,
        subject="repository",
        statement=statement,
        holds=holds,
        rationale=rationale,
    )


def _slug(relative: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", relative.lower()).strip("_")


REPOSITORY_REQUIREMENTS: tuple[Requirement, ...] = (
    *[
        _requirement(
            f"repo.file.{_slug(relative)}",
            f"{relative} is present",
            lambda c, r=relative: c.exists(r),
        )
        for relative in REQUIRED_FILES
    ],
    *[
        _requirement(
            f"repo.migration.{_slug(filename)}",
            f"migration {filename} is present",
            lambda c, f=filename: c.exists(f"apps/api/migrations/versions/{f}"),
            "a migration missing from the tree is a schema step nobody can apply or review",
        )
        for filename in REQUIRED_MIGRATIONS
    ],
    _requirement(
        "repo.json_documents_parse",
        "every shipped JSON contract and schema parses",
        lambda c: not c.invalid_json,
        "a contract that does not parse is a contract nothing enforces",
    ),
    _requirement(
        "repo.closure.target_release",
        "the audit closure targets v5.0.0",
        lambda c: c.closure.get("target_release") == "v5.0.0",
    ),
    _requirement(
        "repo.closure.classifies_every_finding",
        f"the audit closure classifies exactly {EXPECTED_FINDINGS} source findings",
        lambda c: isinstance(c.closure.get("findings"), list)
        and len(c.closure["findings"]) == EXPECTED_FINDINGS,
        "a finding dropped from the register is a finding nobody has to answer for",
    ),
    _requirement(
        "repo.closure.counts_sum",
        f"the closure status counts sum to {EXPECTED_FINDINGS}",
        lambda c: isinstance(c.closure.get("counts"), dict)
        and sum(int(value) for value in c.closure["counts"].values()) == EXPECTED_FINDINGS,
        "counts that do not sum mean a finding is in two states or none",
    ),
    *[
        _requirement(
            f"repo.version.{where}",
            f"{where} declares release {RELEASE_VERSION}",
            check,
            "release identity and its derivative surfaces must agree; one mismatch means "
            "the artefacts describe different builds",
        )
        for where, check in (
            (
                "release_identity",
                lambda c: c.release_identity.get("version") == RELEASE_VERSION
                and c.release_identity.get("tag") == f"v{RELEASE_VERSION}",
            ),
            (
                "api_pyproject",
                lambda c: c.pyproject.get("project", {}).get("version") == RELEASE_VERSION,
            ),
            ("web_package", lambda c: c.package.get("version") == RELEASE_VERSION),
            (
                "runtime_dunder",
                lambda c: "from korpus.release import RELEASE_VERSION as __version__"
                in c.init_text,
            ),
            ("readme_header", lambda c: c.readme.startswith(f"# KORPUS v{RELEASE_VERSION}")),
        )
    ],
    _requirement(
        "repo.no_oversized_files",
        f"no tracked file exceeds {MAX_FILE_BYTES // 1_000_000} MB",
        lambda c: not c.oversized,
        "a large binary in the tree is a thing nobody reviews and everybody clones",
    ),
    _requirement(
        "repo.no_unresolved_placeholders",
        "no shipped source carries an unresolved implementation placeholder",
        lambda c: not c.placeholders,
        "NotImplementedError in a delivered path is a promise the runtime cannot keep",
    ),
    _requirement(
        "repo.no_plaintext_secrets",
        "no plaintext runtime secret is tracked",
        lambda c: not c.tracked_secrets,
        "a secret in the tree is disclosed to everyone who ever clones it, forever",
    ),
)
