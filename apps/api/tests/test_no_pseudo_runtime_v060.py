from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_ROOTS = (ROOT / "apps/api/src/korpus", ROOT / "scripts")


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    result: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            result[child] = parent
    return result


def test_bare_pass_is_only_an_exception_marker_class() -> None:
    violations = []
    for root in PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parents = _parents(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Pass):
                    continue
                parent = parents.get(node)
                allowed = isinstance(parent, ast.ClassDef) and any(
                    (isinstance(base, ast.Name) and base.id.endswith(("Error", "Exception")))
                    or (
                        isinstance(base, ast.Name)
                        and base.id in {"RuntimeError", "ValueError", "PermissionError"}
                    )
                    for base in parent.bases
                )
                if not allowed:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_ellipsis_bodies_exist_only_in_protocol_methods() -> None:
    violations = []
    for root in PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parents = _parents(tree)
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and node.value.value is Ellipsis
                ):
                    continue
                function = parents.get(node)
                cls = parents.get(function) if function is not None else None
                protocol = isinstance(cls, ast.ClassDef) and any(
                    isinstance(base, ast.Name) and base.id == "Protocol" for base in cls.bases
                )
                if not (isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef) and protocol):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []
