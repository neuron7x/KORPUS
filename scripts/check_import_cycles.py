#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "apps/api/src/korpus"
PREFIX = "korpus"


def module_name(path: Path) -> str:
    parts = list(path.relative_to(PACKAGE).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join([PREFIX, *parts]) if parts else PREFIX


def _known_target(candidate: str, known: set[str]) -> str | None:
    while candidate not in known and "." in candidate:
        candidate = candidate.rsplit(".", 1)[0]
    return candidate if candidate in known else None


def _imports(tree: ast.AST, known: set[str]) -> set[str]:
    candidates = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates.extend(alias.name for alias in node.names if alias.name.startswith(PREFIX))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and node.module.startswith(PREFIX)
        ):
            candidates.append(node.module)
    return {target for item in candidates if (target := _known_target(item, known))}


def internal_graph() -> dict[str, set[str]]:
    files = sorted(PACKAGE.rglob("*.py"))
    known = {module_name(path) for path in files}
    graph = {name: set() for name in known}
    for path in files:
        source = module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        graph[source] = _imports(tree, known) - {source}
    return graph


def strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    result: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in graph[node]:
            if neighbor not in indices:
                visit(neighbor)
                low[node] = min(low[node], low[neighbor])
            elif neighbor in on_stack:
                low[node] = min(low[node], indices[neighbor])
        if low[node] == indices[node]:
            component: list[str] = []
            while True:
                current = stack.pop()
                on_stack.remove(current)
                component.append(current)
                if current == node:
                    break
            if len(component) > 1:
                result.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(result)


def main() -> int:
    cycles = strongly_connected(internal_graph())
    print(json.dumps({"valid": not cycles, "cycles": cycles}, indent=2))
    return 0 if not cycles else 1


if __name__ == "__main__":
    raise SystemExit(main())
