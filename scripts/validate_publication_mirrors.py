#!/usr/bin/env python3
"""Та сама публікація під двома URI — «прогалина», якої немає.

`catalog-uri-uniqueness` ловить один документ, заведений двічі під ОДНАКОВИМ `source_uri`.
Але та сама публікація може стояти в каталозі двічі під РІЗНИМИ адресами — офіційний
портал і дзеркало, — і тоді жодне поле не збігається, а документ той самий.

Знайдено виміром, не оглядом: `T3A-FM-3-09` числився серед трьох недосяжних джерел
(`rdl.train.army.mil`, тайм-аут), і його рахували прогалиною корпусу. Насправді це
FM 3-09, який уже лежить у корпусі як `ARTY-FM-3-09-2024`, узятий з armypubs. Тобто
недосяжним було ДЗЕРКАЛО, а не публікація, і «прогалин 3 із 165» було завищене на одну.

Ознака — СЕРІЯ І НОМЕР разом (`FM 3-09`, `ATP 3-12.4`), нормалізовані так, щоб
`3-09` і `3.09` збігались.

**Перша версія лишала серію поза ключем — і це була та сама помилка, яку я вже
спростувала сьогодні виміром.** Тоді структурне правило «той самий номер, різні роки»
дало чотири пари, і текст самих документів спростував УСІ чотири: `ADP 7-0` заміщує
`ADP 7-0`, а не `FM 7-0`; `FM 6-22` заміщує `FM 6-22`, а не `ADP 6-22`. ADP і FM під
одним номером — це різні РІВНІ доктрини, які співіснують, а не копії. Без серії гейт
знаходив 14 «дзеркал», з яких 8 були співіснуванням. Спростоване правило повернулось
у новому файлі через два кроки: помилку прибрано з висновку й лишено в ознаці.

Гейт НЕ вимагає видалення: друга адреса законна як запасна. Він вимагає, щоб зв'язок
був СКАЗАНИЙ — інакше недосяжність дзеркала читається як відсутність документа.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
FIELD = "same_publication_as"
#: Номер шукається в назві, а не в id: id ми складаємо самі, назва приходить із джерела.
PUB = re.compile(r"\b(ATP|FM|TC|ADP|ATTP|AJP|JP|MCTP|MCWP)\s*([0-9][0-9A-Za-z.\-]*)", re.I)


def pub_key(title: str) -> str | None:
    m = PUB.search(title or "")
    if not m:
        return None
    return m.group(1).upper() + " " + m.group(2).upper().replace("-", ".").rstrip(".")


def check(sources: list[dict]) -> list[str]:
    by_id = {s["id"]: s for s in sources}
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in sources:
        key = pub_key(s.get("canonical_title", ""))
        if key:
            groups[key].append(s)

    problems: list[str] = []
    for key, items in sorted(groups.items()):
        uris = {(s.get("source_uri") or "").strip() for s in items}
        if len(items) < 2 or len(uris) < 2:
            #: однаковий URI — це предмет іншого гейта, тут не дублюємо вирок
            continue
        ids = sorted(s["id"] for s in items)
        for s in items:
            named = s.get(FIELD)
            others = [i for i in ids if i != s["id"]]
            if not named:
                problems.append(
                    f"публікація {key}: {len(items)} записів під РІЗНИМИ адресами "
                    f"({', '.join(ids)}); {s['id']} не оголошує `{FIELD}` — недосяжність "
                    f"однієї адреси читатиметься як відсутність документа"
                )
            elif sorted(named if isinstance(named, list) else [named]) != others:
                problems.append(
                    f"{s['id']}: `{FIELD}`={named} не збігається з рештою групи {others}"
                )

    for s in sources:
        named = s.get(FIELD)
        if not named:
            continue
        for other in named if isinstance(named, list) else [named]:
            if other not in by_id:
                problems.append(f"{s['id']}: `{FIELD}` вказує на {other!r}, якого в каталозі немає")
            elif pub_key(by_id[other].get("canonical_title", "")) != pub_key(
                s.get("canonical_title", "")
            ):
                problems.append(
                    f"{s['id']}: оголошено ту саму публікацію, що {other}, але номери "
                    f"різні ({pub_key(s.get('canonical_title', ''))} проти "
                    f"{pub_key(by_id[other].get('canonical_title', ''))})"
                )
    return problems


def selftest() -> int:
    def rec(i: str, title: str, uri: str, **extra: object) -> dict[str, object]:
        return {"id": i, "canonical_title": title, "source_uri": uri, **extra}

    cases: list[tuple[str, list[dict], bool]] = [
        (
            "різні публікації — зелений",
            [rec("A", "FM 3-09 — Fire Support", "u1"), rec("B", "ATP 3-12.4 — EW Platoon", "u2")],
            False,
        ),
        (
            "та сама публікація, різні адреси, без оголошення — червоний",
            [rec("A", "FM 3-09 — Fire Support", "u1"), rec("B", "FM 3-09 — Fire Support", "u2")],
            True,
        ),
        (
            "та сама публікація, різні адреси, оголошено з обох боків — зелений",
            [
                rec("A", "FM 3-09 — Fire Support", "u1", same_publication_as=["B"]),
                rec("B", "FM 3-09 — Fire Support", "u2", same_publication_as=["A"]),
            ],
            False,
        ),
        (
            "оголошено лише з одного боку — червоний",
            [
                rec("A", "FM 3-09 — Fire Support", "u1", same_publication_as=["B"]),
                rec("B", "FM 3-09 — Fire Support", "u2"),
            ],
            True,
        ),
        (
            "той самий URI — предмет іншого гейта, тут зелений",
            [rec("A", "FM 3-09 — Fire Support", "u1"), rec("B", "FM 3-09 — Fire Support", "u1")],
            False,
        ),
        (
            "`3-09` і `3.09` — той самий номер, червоний без оголошення",
            [rec("A", "FM 3-09 — Fire Support", "u1"), rec("B", "FM 3.09 — Fire Support", "u2")],
            True,
        ),
        #: ДОВЕДЕНО СЬОГОДНІ ВИМІРОМ: різні серії під одним номером співіснують.
        #: `ATP 7-100.1` ніде не заявляє заміщення `FM 7-100.1`; `ADP 7-0` заміщує
        #: `ADP 7-0`. Тому такі пари МУСЯТЬ лишатись зеленими.
        (
            "FM 7-100.1 і ATP 7-100.1 — різні серії, співіснують, зелений",
            [rec("A", "FM 7-100.1 — OPFOR", "u1"), rec("B", "ATP 7-100.1 — Russian Tactics", "u2")],
            False,
        ),
        (
            "ADP 7-0 і FM 7-0 — різні рівні доктрини, зелений",
            [rec("A", "ADP 7-0 — Training", "u1"), rec("B", "FM 7-0 — Training", "u2")],
            False,
        ),
        (
            "ATP 3-01.81 і TC 3-01.81 — різні серії, зелений",
            [rec("A", "ATP 3-01.81 — C-UAS", "u1"), rec("B", "TC 3-01.81 — C-UAS", "u2")],
            False,
        ),
        (
            "оголошення на неіснуючий id — червоний",
            [
                rec("A", "FM 3-09 — Fire Support", "u1", same_publication_as=["ZZ"]),
                rec("B", "FM 3-09 — Fire Support", "u2", same_publication_as=["A"]),
            ],
            True,
        ),
        (
            "оголошення між РІЗНИМИ публікаціями — червоний",
            [
                rec("A", "FM 3-09 — Fire Support", "u1", same_publication_as=["B"]),
                rec("B", "ATP 3-12.4 — EW Platoon", "u2", same_publication_as=["A"]),
            ],
            True,
        ),
        (
            "назва без номера публікації — не групується",
            [rec("A", "Бойовий статут", "u1"), rec("B", "Статут внутрішньої служби", "u2")],
            False,
        ),
    ]
    bad = 0
    for name, sources, want_red in cases:
        red = bool(check(sources))
        ok = red == want_red
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}")
    print(f"\nсамоперевірка: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    problems = check(data["sources"] if isinstance(data, dict) else data)
    if problems:
        print(f"publication-mirrors: ВІДМОВЛЕНО — {len(problems)}", file=sys.stderr)
        for p in problems:
            print("  ·", p, file=sys.stderr)
        return 1
    print("publication-mirrors: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
