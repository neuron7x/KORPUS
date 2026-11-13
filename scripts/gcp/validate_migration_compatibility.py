#!/usr/bin/env python3
"""Fail-closed expand/contract policy for production Alembic migrations."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

# Anchor imports to this checkout for both the CLI and package import paths.
SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))
from gcp.migration_add_column_bind import bind_add_column_argument  # noqa: E402
from gcp.migration_check_constraint_scan import inline_check_failure  # noqa: E402
from gcp.migration_column_keyword_scan import (  # noqa: E402
    literal_column_keywords as _column_keywords,
)
from gcp.migration_constraint_proof import constraint_failure as _constraint_failure  # noqa: E402
from gcp.migration_inline_unique_proof import inline_unique_failure  # noqa: E402
from gcp.migration_numeric_default_proof import (  # noqa: E402
    nonnullable_add_without_default as _nonnullable_add_without_default,
)
from gcp.migration_numeric_default_proof import (  # noqa: E402
    unproven_numeric_server_default,
)
from gcp.migration_order_proof import proven_created_before as _created_before  # noqa: E402
from gcp.migration_reachability import reachable_calls as _reachable_calls  # noqa: E402
from gcp.migration_revision_identity import _literal_assignment  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config/production/migration-policy.json"
VERSIONS = ROOT / "apps/api/migrations/versions"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _upgrade_function(tree: ast.Module) -> ast.FunctionDef | None:
    upgrades = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    upgrades = [node for node in upgrades if node.name == "upgrade"]
    return upgrades[0] if len(upgrades) == 1 else None


def _op_call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.attr if func.value.id == "op" else None
    return None


def _literal_nul_default(keywords: dict[str, ast.expr]) -> bool:
    value = keywords.get("server_default")
    return value is not None and any(
        isinstance(node, ast.Constant) and isinstance(node.value, str) and "\0" in node.value
        for node in ast.walk(value)
    )


def _unsafe_add_column(call: ast.Call, created: frozenset[str]) -> str | None:
    if _op_call_name(call) != "add_column":
        return None
    column, problem = bind_add_column_argument(call)
    if problem is not None:
        return problem
    if not isinstance(column, ast.Call):
        return "add_column uses a non-literal Column expression"
    func = column.func
    is_column = isinstance(func, ast.Attribute) and ast.unparse(func) == "sa.Column"
    if not is_column:
        return "add_column second argument is not a Column constructor"
    keywords = _column_keywords(column)
    if keywords is None:
        return "unverified Column keyword expansion or duplicated keys"
    if (unique_problem := inline_unique_failure(call, keywords, created)) is not None:
        return unique_problem
    if _literal_nul_default(keywords):
        return "literal server_default contains NUL character"
    if (check_reason := inline_check_failure(column, keywords)) is not None:
        return check_reason
    if (default_problem := unproven_numeric_server_default(column, keywords)) is not None:
        return default_problem
    if _nonnullable_add_without_default(keywords):
        return "non-null column without server_default is not expand-safe for existing rows"
    return None


def _verify_baseline(current: dict[str, Path], baseline: dict[str, str]) -> list[str]:
    findings: list[str] = []
    for relative, expected in sorted(baseline.items()):
        path = current.get(relative)
        if path is None:
            findings.append(f"baseline migration missing: {relative}")
        elif _sha256(path) != expected:
            findings.append(f"baseline migration mutated: {relative}")
    return findings


_RAW_CREATE_TABLE = re.compile(r"create\s+table\s+[a-z_][a-z_0-9]*\s*\([^;]*\)", re.S | re.I)


def _altered_table(statement: str) -> str | None:
    """Ім'я таблиці в `ALTER TABLE <ім'я> …`, якщо його видно дослівно."""
    if match := re.match(r'(?i)^alter\s+table\s+("[^"]+"|[a-z_]\w*)\s', statement):
        name = match.group(1)
        return name[1:-1] if name.startswith('"') else name.lower()
    return None


def _execute_is_expanding(node: ast.Call, created: frozenset[str] = frozenset()) -> str | None:
    """None означає «розширювальне і дозволене»; рядок — причину відмови.

    Нелітеральний аргумент НЕ проходить: судити його зсередини неможливо, а
    невідоме не є дозволом.

    `ALTER TABLE` пропускається РІВНО тоді, коли таблицю створює ця сама міграція.
    `ALTER TABLE` on an existing table can narrow the N-1 read contract.
    Same-migration tables cannot affect N-1; their literal ALTER is admissible.
    Preserve this distinction instead of banning every ALTER by verb.
    """
    if not node.args:
        return "op.execute without a statement"
    first = node.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return "op.execute requires a literal SQL statement"
    statement = first.value.strip()
    if any(marker in statement for marker in (";", "--", "/*", "*/", "\x00")):
        return "op.execute with stacked or commented SQL is not expand-safe"
    if _RAW_CREATE_TABLE.fullmatch(statement):
        return None
    table = _altered_table(statement)
    if table is not None:
        if table in created:
            return None
        return f"op.execute(ALTER TABLE {table} …) над таблицею, якої ця міграція не створює"
    verb = statement.split(maxsplit=1)[0] if statement else "?"
    return f"op.execute({verb.upper()} …)"


def _inspect_future(path: Path, relative: str, tree: ast.Module, forbidden: set[str]) -> list[str]:
    upgrade = _upgrade_function(tree)
    if upgrade is None:
        return [f"future migration has no unique upgrade(): {relative}"]
    calls, dispatch_failures = _reachable_calls(tree, upgrade)
    findings = [
        f"future migration is not expand-only: {relative}: {reason}" for reason in dispatch_failures
    ]
    created = _created_before(tree, upgrade)
    for node in calls:
        eligible = created.get(id(node), frozenset())
        opname = _op_call_name(node)
        if opname in forbidden:
            reason = (
                _execute_is_expanding(node, eligible) if opname == "execute" else "op." + opname
            )
            if reason is not None:
                findings.append(f"future migration is not expand-only: {relative}: {reason}")
        reason = _unsafe_add_column(node, eligible) or _constraint_failure(node, eligible)
        if reason:
            findings.append(f"future migration is not expand-only: {relative}: {reason}")
    return findings


def _inspect_history(
    current: dict[str, Path], baseline: dict[str, str], forbidden: set[str]
) -> tuple[dict[str, tuple[str | None, str]], list[Path], list[str]]:
    revisions: dict[str, tuple[str | None, str]] = {}
    future: list[Path] = []
    findings: list[str] = []
    for relative, path in current.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        revision, down = (
            _literal_assignment(tree, "revision"),
            _literal_assignment(tree, "down_revision"),
        )
        if not revision:
            findings.append(f"migration has no literal revision: {relative}")
            continue
        if revision in revisions:
            findings.append(f"duplicate revision: {revision}")
        revisions[revision] = (down, relative)
        if relative not in baseline:
            future.append(path)
            findings.extend(_inspect_future(path, relative, tree, forbidden))
    return revisions, future, findings


def _verify_graph(
    revisions: dict[str, tuple[str | None, str]], baseline_revision: str
) -> tuple[list[str], list[str]]:
    children: dict[str | None, list[str]] = {}
    for revision, (down, _) in revisions.items():
        children.setdefault(down, []).append(revision)
    findings: list[str] = []
    forks = {
        parent: vals for parent, vals in children.items() if parent is not None and len(vals) > 1
    }
    if forks:
        findings.append(f"migration history forks are forbidden in production lane: {forks}")
    heads = sorted(set(revisions) - {down for down, _ in revisions.values() if down})
    if len(heads) != 1:
        findings.append(f"exactly one migration head required, got {heads}")
    if baseline_revision not in revisions:
        findings.append(f"baseline revision absent: {baseline_revision}")
    if len(heads) == 1:
        seen: set[str] = set()
        current: str | None = heads[0]
        while current is not None and current in revisions and current not in seen:
            seen.add(current)
            current = revisions[current][0]
        if current is not None:
            findings.append(f"migration lineage cycle or missing parent: {current}")
        if len(seen) != len(revisions):
            findings.append(f"disconnected migration revisions: {sorted(set(revisions) - seen)}")
    return heads, findings


def evaluate(root: Path = ROOT) -> dict[str, Any]:
    policy = json.loads((root / POLICY.relative_to(ROOT)).read_text(encoding="utf-8"))
    versions = root / VERSIONS.relative_to(ROOT)
    baseline: dict[str, str] = policy["baseline_files"]
    current = {str(p.relative_to(root)): p for p in sorted(versions.glob("*.py"))}
    findings = _verify_baseline(current, baseline)
    revisions, future, history_findings = _inspect_history(
        current, baseline, set(policy["future_upgrade_forbidden_calls"])
    )
    findings.extend(history_findings)
    heads, graph_findings = _verify_graph(revisions, policy["baseline_revision"])
    findings.extend(graph_findings)
    return {
        "schema": "korpus.migration-compatibility-report.v1",
        "status": "FAIL" if findings else "PASS",
        "baseline_revision": policy["baseline_revision"],
        "baseline_files": len(baseline),
        "future_migrations": len(future),
        "head": heads[0] if len(heads) == 1 else None,
        "findings": findings,
    }


def main() -> int:
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
