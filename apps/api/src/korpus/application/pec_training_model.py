"""Small deterministic rule-tree trainer for offline PEC calibration.

This module is development/offline logic only.  The production API consumes the exported
rule profile and has no ML dependency.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, cast

from korpus.application.controller_profile import RuleCondition
from korpus.application.evidence_state import FEATURE_NAMES
from korpus.application.numeric_contracts import finite_number, require_count


@dataclass(frozen=True, slots=True)
class TrainingRow:
    query_id: str
    group_id: str
    features: Mapping[str, object]
    label: str


@dataclass(frozen=True, slots=True)
class TreeLeaf:
    leaf_id: str
    conditions: tuple[RuleCondition, ...]
    action: str
    training_samples: int


@dataclass(frozen=True, slots=True)
class TreeModel:
    max_depth: int
    min_leaf: int
    leaves: tuple[TreeLeaf, ...]

    def predict_leaf(self, features: Mapping[str, object]) -> TreeLeaf | None:
        for leaf in self.leaves:
            if all(_matches(features.get(c.feature), c) for c in leaf.conditions):
                return leaf
        return None

    def predict(self, features: Mapping[str, object]) -> str:
        leaf = self.predict_leaf(features)
        return leaf.action if leaf is not None else "BASELINE"


def _matches(actual: object, condition: RuleCondition) -> bool:
    expected = condition.value
    op = condition.operator
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        return False
    if not finite_number(actual) or not finite_number(expected):
        return False
    return {
        "lt": actual < expected,
        "le": actual <= expected,
        "gt": actual > expected,
        "ge": actual >= expected,
    }.get(op, False)


def _majority(rows: list[TrainingRow]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.label] = counts.get(row.label, 0) + 1
    return min(counts, key=lambda label: (-counts[label], label))


def _errors(rows: list[TrainingRow]) -> int:
    if not rows:
        return 0
    winner = _majority(rows)
    return sum(row.label != winner for row in rows)


def _candidates(rows: list[TrainingRow]) -> Iterable[RuleCondition]:
    for feature in FEATURE_NAMES:
        values = [row.features.get(feature) for row in rows if feature in row.features]
        if len(values) < 2:
            continue
        unique = sorted(set(values), key=lambda x: (type(x).__name__, str(x)))
        if all(isinstance(v, bool) for v in unique):
            yield RuleCondition(feature=feature, operator="eq", value=True)
            continue
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in unique):
            if not all(finite_number(v) for v in unique):
                raise ValueError(f"PEC training feature {feature!r} must be finite")
            numeric = sorted(float(cast(Any, v)) for v in unique)
            if len(numeric) > 24:
                step = max(1, len(numeric) // 24)
                numeric = numeric[::step]
            for left, right in pairwise(numeric):
                if left != right:
                    yield RuleCondition(feature=feature, operator="le", value=(left + right) / 2)
            continue
        for value in unique[:16]:
            if isinstance(value, str):
                yield RuleCondition(feature=feature, operator="eq", value=value)


def _split(
    rows: list[TrainingRow], condition: RuleCondition
) -> tuple[list[TrainingRow], list[TrainingRow]]:
    left = [row for row in rows if _matches(row.features.get(condition.feature), condition)]
    right = [row for row in rows if row not in left]
    return left, right


def _best_split(
    rows: list[TrainingRow], min_leaf: int
) -> tuple[RuleCondition, list[TrainingRow], list[TrainingRow]] | None:
    base = _errors(rows)
    best = None
    best_key = None
    for condition in _candidates(rows):
        left, right = _split(rows, condition)
        if len(left) < min_leaf or len(right) < min_leaf:
            continue
        gain = base - _errors(left) - _errors(right)
        key = (-gain, condition.feature, condition.operator, str(condition.value))
        if gain > 0 and (best_key is None or key < best_key):
            best = (condition, left, right)
            best_key = key
    return best


def train_tree(rows: Iterable[TrainingRow], *, max_depth: int, min_leaf: int) -> TreeModel:
    data = list(rows)
    if not data:
        raise ValueError("PEC training requires rows")
    max_depth = require_count(max_depth, label="max_depth")
    min_leaf = require_count(min_leaf, positive=True, label="min_leaf")
    leaves: list[TreeLeaf] = []

    def walk(node: list[TrainingRow], depth: int, path: tuple[RuleCondition, ...]) -> None:
        split = (
            None
            if depth >= max_depth or len(node) < 2 * min_leaf or _errors(node) == 0
            else _best_split(node, min_leaf)
        )
        if split is None:
            leaves.append(TreeLeaf(f"leaf-{len(leaves):03d}", path, _majority(node), len(node)))
            return
        condition, left, right = split
        walk(left, depth + 1, (*path, condition))
        inverse = {"le": "gt", "lt": "ge", "ge": "lt", "gt": "le", "eq": "ne", "ne": "eq"}[
            condition.operator
        ]
        walk(
            right,
            depth + 1,
            (
                *path,
                RuleCondition(feature=condition.feature, operator=inverse, value=condition.value),
            ),
        )

    walk(data, 0, ())
    return TreeModel(max_depth, min_leaf, tuple(leaves))
