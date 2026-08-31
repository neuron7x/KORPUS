#!/usr/bin/env python3
"""Нове підняття стелі модуля мусить бути НАЗВАНЕ в `raised`.

`config/operations/module-budget.json` каже про себе: «Ceilings above the default
record what was measured that day and may only be lowered.» Правило записане, і
до цього гейта його не читав ЖОДЕН код: списки `raised` і `lowered` існували як
документація. Стелю можна було підняти мовчки, і жодна перевірка б не моргнула.

Виміряно 30.08.2026: 97 із 516 модулів мають стелю вище дефолту без записаної
причини, а самі записи в `raised` існують у ШЕСТИ різних формах. Тому гейт не
вимагає причини для всього наявного — це дало б 97 червоних і був би не гейт, а
завал. Він охороняє МАЙБУТНЄ: наявні стелі стають базою, а кожне НОВЕ підняття
мусить назвати себе.

Порівнюється версія з HEAD і версія в дереві. Зниження дозволене мовчки —
ратчет і існує, щоб рухатись униз. Підняття без запису — відмова.

    check_budget_raises_are_named.py [--base HEAD]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUDGET = "config/operations/module-budget.json"

#: Ключі стелі. Підняття будь-якого з них — підняття.
CEILINGS = ("lines", "max_complexity", "max_function_lines", "max_function_args", "max_nesting")


def _recorded_raises(document: dict[str, Any]) -> dict[str, set[tuple[str, int]]]:
    """Стелі, ЗАПИСАНІ в `raised`, прив'язані до шляху і до самого числа.

    Раніше тут збиралися самі ШЛЯХИ, і перевірка звучала «чи згадано цей файл у
    `raised`». Виміряно 31.08.2026: `scripts/run_mutation_tests.py` уже мав три
    записи, тож підняття 4400 → 4494 пройшло з вердиктом PASS і порожнім
    `unnamed_raises`. Один раз названий файл ставав вільним НАЗАВЖДИ, а таких
    файлів у списку на той день було стільки ж, скільки записів. Гейт охороняв
    сусіднє: наявність згадки замість наявності причини саме для цього підняття.

    Тепер запис мусить назвати число, до якого піднімають. Форми лишаються всі
    шість — вимагати однієї означало б відкинути сумлінні записи, — але з кожної
    береться пара (ключ стелі, нове значення).
    """
    recorded: dict[str, set[tuple[str, int]]] = {}

    def remember(path: object, to: object) -> None:
        if not isinstance(path, str) or not isinstance(to, dict):
            return
        for key in CEILINGS:
            value = to.get(key)
            if isinstance(value, int):
                recorded.setdefault(path, set()).add((key, value))

    for record in document.get("raised", ()):
        if not isinstance(record, dict):
            continue
        remember(record.get("path"), record.get("to"))
        for path in record.get("paths", ()) or ():
            remember(path, record.get("to"))
        for nested in (*(record.get("entries") or ()), *(record.get("changes") or ())):
            if isinstance(nested, dict):
                # Вкладений запис має право нести власне число; якщо він його не несе,
                # береться число зовнішнього запису — інакше сумлінна вкладена форма
                # втратила б чинність через те, де саме лежить `to`.
                remember(nested.get("path"), nested.get("to") or record.get("to"))
    return recorded


def _ceilings(document: dict[str, Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for path, module in (document.get("modules") or {}).items():
        if not isinstance(module, dict):
            continue
        out[path] = {k: module[k] for k in CEILINGS if isinstance(module.get(k), int)}
    return out


def raises_without_a_reason(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Модулі, чия стеля зросла й ніде не названа."""
    old, new = _ceilings(before), _ceilings(after)
    recorded = _recorded_raises(after)
    offenders: list[str] = []
    for path, ceilings in new.items():
        previous = old.get(path)
        if previous is None:
            continue  # новий модуль отримує стелю вперше, а не піднімає її
        named = recorded.get(path, set())
        grown = [
            k
            for k, v in ceilings.items()
            if k in previous and v > previous[k] and (k, v) not in named
        ]
        if grown:
            detail = ", ".join(f"{k} {previous[k]}→{ceilings[k]}" for k in grown)
            offenders.append(f"{path}: {detail} — підняття не назване в `raised`")
    return offenders


def _at(revision: str) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "show", f"{revision}:{BUDGET}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}
    document = json.loads(result.stdout)
    # `json.loads` віддає Any: JSON цілком законно може бути списком або числом.
    # Порожній словник тут — не «немає стель», а «порівнювати нема з чим», і
    # `main` віддає на це UNKNOWN, а не PASS.
    return document if isinstance(document, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(prog="check_budget_raises_are_named")
    parser.add_argument("--base", default="HEAD")
    args = parser.parse_args()

    before = _at(args.base)
    if not before:
        # Порожня база — не привід пропустити: без неї порівняння не відбулось,
        # а не «пройшло». Мовчазне зелене тут коштувало б рівно того, проти чого
        # гейт написаний.
        print(
            json.dumps(
                {
                    "schema": "korpus.budget-raise-check.v1",
                    "status": "UNKNOWN",
                    "reason": f"{BUDGET} недоступний у {args.base}",
                },
                ensure_ascii=False,
            )
        )
        return 2
    after = json.loads((ROOT / BUDGET).read_text(encoding="utf-8"))
    offenders = raises_without_a_reason(before, after)
    print(
        json.dumps(
            {
                "schema": "korpus.budget-raise-check.v1",
                "status": "FAIL" if offenders else "PASS",
                "base": args.base,
                "unnamed_raises": offenders,
                "interpretation": (
                    "Наявні стелі — база, не борг цього гейта. Він відмовляє лише новому "
                    "підняттю, яке не назвало причини."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
