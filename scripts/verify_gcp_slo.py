#!/usr/bin/env python3
"""Контракт SLO: перевірка, яка тепер ОБОВ'ЯЗКОВА в конвеєрі, тож мусить уміти впасти.

Вирок будувався як `all(item.passed for item in predicates)`. `all([])` істинне, тож
порожній перелік предикатів давав PASS із `total: 0` — «не виміряно» ставало «пройдено».
Сьогодні `evaluate()` повертає літеральний список і порожнім не буває, але вирок не
сміє триматися на цьому: `evaluate_request_sli()` вливається в той самий список, і
досить йому колись повернути порожньо, щоб гейт мовчки перестав щось перевіряти.

Виміряно 04.09.2026, коли `gcp:production-contract` внесли до обов'язкових джобів: у
скрипта не було ні самоперевірки, ні жодного тесту, що його імпортує.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gcp.slo_contract import evaluate


def judge(predicates: list[Any]) -> dict[str, Any]:
    """Вирок про перелік предикатів. Порожній перелік — НЕ успіх."""
    total = len(predicates)
    passed = sum(bool(getattr(item, "passed", False)) for item in predicates)
    return {
        "status": "PASS" if total and passed == total else "FAIL",
        "total": total,
        "passed": passed,
        "detail": (
            "контракт не назвав жодного предиката — не виміряно, не пройдено"
            if not total
            else f"{passed}/{total} предикатів контракту"
        ),
        "predicates": [dict(vars(item)) for item in predicates],
    }


class _Predicate:
    def __init__(self, name: str, passed: bool) -> None:
        self.name = name
        self.passed = passed


def selftest() -> int:
    """Негативні контролі: порожньо ≠ зелено, і один хибний предикат валить усе."""
    checks: list[tuple[str, Any, Any]] = [
        ("усі предикати істинні — PASS", judge([_Predicate("a", True)])["status"], "PASS"),
        (
            "один хибний предикат валить контракт",
            judge([_Predicate("a", True), _Predicate("b", False)])["status"],
            "FAIL",
        ),
        ("порожній перелік — НЕ успіх (all([]) істинне)", judge([])["status"], "FAIL"),
        ("порожній перелік називає причину", "не виміряно" in judge([])["detail"], True),
        ("лічильник рахує пройдені, не всі", judge([_Predicate("a", False)])["passed"], 0),
        ("total — це довжина переліку", judge([_Predicate("a", True)] * 3)["total"], 3),
    ]
    passed = 0
    for name, got, want in checks:
        ok = got == want
        passed += ok
        print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: {got!r}")
    print(f"негативний контроль: {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    payload = judge(list(evaluate(args.root)))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
