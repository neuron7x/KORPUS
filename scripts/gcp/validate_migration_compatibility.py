#!/usr/bin/env python3
"""Fail-closed expand/contract policy for production Alembic migrations."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config/production/migration-policy.json"
VERSIONS = ROOT / "apps/api/migrations/versions"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _literal_assignment(tree: ast.Module, name: str) -> str | None:
    for node in tree.body:
        value: ast.expr | None = None
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ) or (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
        ):
            value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


def _upgrade_function(tree: ast.Module) -> ast.FunctionDef | None:
    return next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"), None
    )


def _op_call_name(call: ast.Call) -> str | None:
    func = call.func
    return (
        func.attr
        if isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "op"
        else None
    )


def _unsafe_add_column(call: ast.Call) -> str | None:
    if _op_call_name(call) != "add_column" or len(call.args) < 2:
        return None
    column = call.args[1]
    if not isinstance(column, ast.Call):
        return "add_column uses a non-literal Column expression"
    func = column.func
    is_column = (isinstance(func, ast.Attribute) and func.attr == "Column") or (
        isinstance(func, ast.Name) and func.id == "Column"
    )
    if not is_column:
        return "add_column second argument is not a Column constructor"
    keywords = {kw.arg: kw.value for kw in column.keywords if kw.arg}
    nullable, default = keywords.get("nullable"), keywords.get("server_default")
    if (
        isinstance(nullable, ast.Constant)
        and nullable.value is False
        and (default is None or (isinstance(default, ast.Constant) and default.value is None))
    ):
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


#: Дієслова, які лише ДОДАЮТЬ. `op.execute` — це інструмент, а не операція: єдиний
#: спосіб створити тригер в alembic, і водночас спосіб знести таблицю. Заборона на
#: сам виклик не розрізняє розширення від руйнування, тобто перевірка з іменем
#: «expand-only» міряє механізм, а не властивість, яку охороняє.
_EXPANDING_VERBS = ("create ",)


def _execute_is_expanding(node: ast.Call) -> str | None:
    """None означає «розширювальне і дозволене»; рядок — причину відмови.

    Нелітеральний аргумент НЕ проходить: судити його зсередини неможливо, а
    невідоме не є дозволом.
    """
    if not node.args:
        return "op.execute without a statement"
    first = node.args[0]
    parts: list[str] = []
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        parts = [first.value]
    elif isinstance(first, ast.JoinedStr):
        parts = [
            v.value
            for v in first.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ]
    if not parts:
        return "op.execute with a statement this gate cannot read"
    statement = " ".join(parts).lstrip().lower()
    if statement.startswith(_EXPANDING_VERBS):
        return None
    verb = statement.split(" ", 1)[0] or "?"
    return f"op.execute({verb.upper()} …)"


def _inspect_future(path: Path, relative: str, tree: ast.Module, forbidden: set[str]) -> list[str]:
    upgrade = _upgrade_function(tree)
    if upgrade is None:
        return [f"future migration has no upgrade(): {relative}"]
    findings: list[str] = []
    for node in ast.walk(upgrade):
        if not isinstance(node, ast.Call):
            continue
        opname = _op_call_name(node)
        if opname in forbidden:
            reason = _execute_is_expanding(node) if opname == "execute" else "op." + opname
            if reason is not None:
                findings.append(f"future migration is not expand-only: {relative}: {reason}")
        reason = _unsafe_add_column(node)
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
