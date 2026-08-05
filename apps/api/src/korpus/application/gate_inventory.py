"""Enumerate the predicates the release gates evaluate.

§2.8 of the admission boundary is the standing one: four gates were shown to be
incapable of failing, and closing those four proves nothing about the fifth. The
requirement is not "these gates can go red" but "every gate can, including the ones
written after this sentence".

That needs the list of predicates to be derived from the code rather than maintained by
hand, so a predicate added tomorrow appears here without anyone remembering to add it.
The names are read with `ast` from the dictionary literals the aggregators build: a
predicate that is not in one of those dictionaries is not a predicate the gate reports.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from typing import Any

from korpus.application.assurance import evaluate_assurance
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
    indent = min(
        (len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0
    )
    return "\n".join(line[indent:] if len(line) >= indent else line for line in lines)


def operational_predicates() -> tuple[str, ...]:
    return _dictionary_keys(OperationalReleaseGate.evaluate, "checks")


def assurance_predicates() -> tuple[str, ...]:
    return _dictionary_keys(evaluate_assurance, "checks")


def all_predicates() -> dict[str, tuple[str, ...]]:
    """Every reported predicate, by the gate that reports it."""

    return {
        "operational": operational_predicates(),
        "assurance": assurance_predicates(),
    }
