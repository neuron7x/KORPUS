"""Enumerate every predicate emitted by release gates.

The inventory is derived from executable reporting surfaces so refactors cannot
silently erase negative-control obligations.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from typing import Any

from korpus.application.assurance import evaluate_assurance
from korpus.application.operational_math import evaluate_operational_checks
from korpus.application.operations import OperationalReleaseGate


def _dictionary_keys(function: Callable[..., Any], variable: str) -> tuple[str, ...]:
    """Keys of the `variable = {...}` literal inside `function`."""

    source = inspect.getsource(function)
    tree = ast.parse(ast.unparse(ast.parse(_dedent(source))))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if variable not in targets:
            continue
        keys = [
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        ]
        return tuple(keys)
    raise LookupError(f"no dictionary named {variable!r} in {function.__qualname__}")


def _dedent(source: str) -> str:
    lines = source.splitlines()
    indent = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    return "\n".join(line[indent:] if len(line) >= indent else line for line in lines)


def operational_predicates() -> tuple[str, ...]:
    outer = _dictionary_keys(OperationalReleaseGate.evaluate, "checks")
    delegated = evaluate_operational_checks({}, {}, {}, {}, {}, {}, {}, {})
    return (*outer, *delegated)


def assurance_predicates() -> tuple[str, ...]:
    return _dictionary_keys(evaluate_assurance, "checks")


def all_predicates() -> dict[str, tuple[str, ...]]:
    """Every reported predicate, by the gate that reports it."""

    return {
        "operational": operational_predicates(),
        "assurance": assurance_predicates(),
    }
