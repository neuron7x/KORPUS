#!/usr/bin/env python3
"""Звіт мутацій, що описує ІНШИЙ каталог, виглядає точно як свіжий.

Двічі за 31.08.2026 `reports/MUTATION_REPORT.json` розійшовся з кодом і обидва рази
пережив зелений `make validate`:

    ранок   звіт 379 мутантів   каталог 385   (звіт на добу старший)
    вечір   звіт 385 мутантів   каталог 390   (нові правила без прогону)

Обидва рази число «убито 100 %» лишалось на місці й читалось як доказ, хоча описувало
набір правил, якого в дереві вже немає. Жоден гейт цього не питав: `verify_current_truth`
тримає власний перелік звітів, і цього в ньому немає, а `snapshot` уміє лише не
переносити ПОГАНЕ — не помічати ЗАСТАРІЛЕ.

Правило просте й не про дайджести дерева: звіт мусить називати ТОЙ САМИЙ набір мутантів,
що й каталог у коді. Порівнюється МНОЖИНА ідентифікаторів, а не лише кількість: додати
один мутант і прибрати інший лишає число незмінним, і саме такий обмін гейт на лічильнику
пропустив би.

Звіт БЕЗ провенансу відхиляється окремо: він не каже, яке дерево його зробило, а
непідв'язаний PASS гірший за відсутній, бо виглядає як доказ.

Коди виходу: 0 — збігається · 1 — відхилено · 2 — сам гейт не зміг виміряти.
Розрізняти обов'язково: непійманий виняток у Python виходить з 1, як і свідома відмова,
і агрегатор бачить «гейт відхилив» там, де насправді «гейт упав».
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/MUTATION_REPORT.json"


def catalogue_ids() -> set[str]:
    """Ідентифікатори з КОДУ, не з копії переліку.

    Імпорт, а не розбір тексту: копія переліку розійшлася б із каталогом мовчки — рівно
    той дефект, який цей гейт існує ловити.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_mutation_tests import MUTANTS

    return {mutant.id for mutant in MUTANTS}


def problems(report: dict[str, Any], expected: set[str]) -> list[str]:
    found: list[str] = []
    provenance = report.get("provenance")
    if not isinstance(provenance, dict) or not provenance.get("source_digest"):
        found.append(
            "звіт не несе провенансу: він не каже, яке дерево його зробило, "
            "а непідв'язаний PASS гірший за відсутній"
        )
    results = report.get("results")
    if not isinstance(results, list):
        return [*found, "у звіті немає переліку результатів — порівнювати нема з чим"]
    reported = {str(row.get("id")) for row in results if isinstance(row, dict)}
    missing = sorted(expected - reported)
    extra = sorted(reported - expected)
    if missing:
        found.append(f"каталог має {len(missing)} мутантів, яких звіт не бачив: {missing[:5]}")
    if extra:
        found.append(f"звіт називає {len(extra)} мутантів, яких у каталозі немає: {extra[:5]}")
    declared = report.get("mutants")
    if declared != len(reported):
        found.append(f"звіт оголошує {declared} мутантів, а результатів {len(reported)}")
    # Звіт провального прогону не має лежати в `reports/` як доказ: там живе те, на що
    # посилаються інші гейти, і «вижив один» під заголовком 100 % читається як 100 %.
    for key in ("survived", "invalid", "errors"):
        rows = report.get(key)
        if rows:
            found.append(f"звіт містить непорожній `{key}` ({len(rows)}) — це не доказ проходження")
    return found


def selftest() -> int:
    """Отрути по ДАНИХ: кожна створює вхід, на якому гейт зобов'язаний спрацювати.

    Отрута на КОД гейта не розрізняє «перевірка мертва» і «перевірка тривіальна на цих
    даних» — а це протилежні речі.
    """
    expected = {"M01", "M02", "M03"}
    good: dict[str, Any] = {
        "mutants": 3,
        "results": [{"id": "M01"}, {"id": "M02"}, {"id": "M03"}],
        "provenance": {"source_digest": "0" * 64},
        "survived": [],
        "invalid": [],
        "errors": [],
    }
    rows: list[dict[str, str]] = [{"id": "M01"}, {"id": "M02"}, {"id": "M03"}]
    cases: list[tuple[str, dict[str, Any], bool]] = [
        ("чистий стан приймається", good, False),
        (
            "мутанта додано в код, у звіті його немає",
            {**good, "results": rows[:2], "mutants": 2},
            True,
        ),
        (
            "звіт називає мутанта, якого немає в каталозі",
            {**good, "results": [*rows, {"id": "M99"}], "mutants": 4},
            True,
        ),
        (
            "ОБМІН: один прибрано, інший додано — кількість та сама",
            {**good, "results": [{"id": "M01"}, {"id": "M02"}, {"id": "M99"}]},
            True,
        ),
        ("лічильник розходиться з переліком", {**good, "mutants": 7}, True),
        ("звіт без провенансу", {k: v for k, v in good.items() if k != "provenance"}, True),
        ("звіт із вижилим мутантом", {**good, "survived": ["M02"]}, True),
        ("звіт без переліку результатів", {k: v for k, v in good.items() if k != "results"}, True),
    ]
    failures: list[str] = []
    for name, payload, must_reject in cases:
        rejected = bool(problems(payload, expected))
        if rejected != must_reject:
            failures.append(f"{name}: очікували {'відхилення' if must_reject else 'проходження'}")
    print(json.dumps({"selftest": len(cases), "failed": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not REPORT.is_file():
        print(json.dumps({"status": "UNKNOWN", "reason": f"немає {REPORT}"}, ensure_ascii=False))
        return 2
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    found = problems(report, catalogue_ids())
    print(
        json.dumps(
            {"status": "FAIL" if found else "PASS", "problems": found},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if found else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:
        # Аварія гейта — це 2, а не 1. Інакше «не зміг виміряти» приходить агрегатору
        # як «виміряв і відхилив», і UNKNOWN тихо стає FAIL.
        print(
            json.dumps(
                {"status": "ERROR", "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False
            )
        )
        raise SystemExit(2) from error
