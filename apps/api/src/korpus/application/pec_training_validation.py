"""Group-aware and nested validation for offline PEC controller training."""
from __future__ import annotations

import hashlib
from collections.abc import Iterable

from korpus.application.pec_training_model import train_tree
from korpus.application.statistical_bounds import hoeffding_upper_bound


def _bucket(group_id: str, folds: int) -> int:
    digest = hashlib.sha256(group_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % folds


def grouped_folds(rows: Iterable[object], folds: int = 5) -> list[tuple[list[object], list[object]]]:
    if folds < 2:
        raise ValueError("PEC grouped validation requires at least two folds")
    data = list(rows)
    buckets = {group: _bucket(group, folds) for group in sorted({row.group_id for row in data})}
    return [
        ([row for row in data if buckets[row.group_id] != index], [row for row in data if buckets[row.group_id] == index])
        for index in range(folds)
    ]


def _candidates(data: list[object]) -> list[tuple[int, int]]:
    return [(depth, leaf) for depth in (1, 2, 3, 4) for leaf in (5, 10, 20, 30) if len(data) >= 2 * leaf]


def select_hyperparameters(rows: Iterable[object]) -> tuple[int, int, dict[str, object]]:
    data = list(rows)
    scored: list[tuple[float, int, int, int, int, int]] = []
    for depth, min_leaf in _candidates(data):
        correct = total = 0
        for train, valid in grouped_folds(data):
            if not train or not valid or len(train) < 2 * min_leaf:
                continue
            model = train_tree(train, max_depth=depth, min_leaf=min_leaf)
            correct += sum(model.predict(row.features) == row.label for row in valid)
            total += len(valid)
        accuracy = correct / total if total else -1.0
        scored.append((accuracy, -depth, min_leaf, depth, min_leaf, total))
    if not scored:
        raise ValueError("insufficient grouped data for PEC hyperparameter selection")
    best = max(scored)
    return best[3], best[4], {"grouped_cv_accuracy": best[0], "validation_rows": best[5], "candidates": len(scored)}


def nested_group_validation(rows: Iterable[object], outer_folds: int = 5) -> dict[str, object]:
    """Estimate generalization with hyperparameter selection confined to each outer train split."""
    data = list(rows)
    results: list[dict[str, object]] = []
    correct = total = 0
    for index, (outer_train, outer_valid) in enumerate(grouped_folds(data, outer_folds)):
        if not outer_train or not outer_valid:
            continue
        try:
            depth, min_leaf, inner = select_hyperparameters(outer_train)
        except ValueError:
            continue
        model = train_tree(outer_train, max_depth=depth, min_leaf=min_leaf)
        fold_correct = sum(model.predict(row.features) == row.label for row in outer_valid)
        correct += fold_correct
        total += len(outer_valid)
        train_groups = {row.group_id for row in outer_train}
        valid_groups = {row.group_id for row in outer_valid}
        results.append({
            "fold": index,
            "train_rows": len(outer_train),
            "validation_rows": len(outer_valid),
            "correct": fold_correct,
            "max_depth": depth,
            "min_leaf": min_leaf,
            "inner_cv": inner,
            "group_disjoint": train_groups.isdisjoint(valid_groups),
        })
    covered = total == len(data) and bool(data)
    disjoint = bool(results) and all(bool(item["group_disjoint"]) for item in results)
    status = "PASS" if covered and disjoint and len(results) >= 2 else "UNKNOWN"
    return {
        "status": status,
        "outer_folds_requested": outer_folds,
        "outer_folds_evaluated": len(results),
        "rows": len(data),
        "evaluated_rows": total,
        "oof_accuracy": correct / total if total else None,
        "group_disjoint": disjoint,
        "folds": results,
    }


def hoeffding_upper(errors: int, samples: int, delta: float) -> float:
    return hoeffding_upper_bound(errors, samples, delta)
