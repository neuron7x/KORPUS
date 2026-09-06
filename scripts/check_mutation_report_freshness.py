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
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.provenance import compute_source_digest  # noqa: E402

REPORT = ROOT / "reports/MUTATION_REPORT.json"


def catalogue_ids() -> set[str]:
    """Ідентифікатори з КОДУ, не з копії переліку.

    Імпорт, а не розбір тексту: копія переліку розійшлася б із каталогом мовчки — рівно
    той дефект, який цей гейт існує ловити.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_mutation_tests import MUTANTS

    return {mutant.id for mutant in MUTANTS}


def binding_problems(report: dict[str, Any], source_digest: str | None) -> list[str]:
    """Чи звіт каже, про яке дерево він, і чи це ТЕ САМЕ дерево.

    Винесено з `problems()` окремо не заради стилю: разом вони давали складність 13
    при стелі 10, а стеля тут — ратчет, який не піднімають, бо функція виросла.
    Дві різні відмови — «не сказано» і «сказано про інше» — читаються нарізно.
    """
    provenance = report.get("provenance")
    carried = provenance.get("source_digest") if isinstance(provenance, dict) else None
    if not isinstance(provenance, dict) or not carried:
        return [
            "звіт не несе провенансу: він не каже, яке дерево його зробило, "
            "а непідв'язаний PASS гірший за відсутній"
        ]
    if source_digest and carried != source_digest:
        return [
            f"звіт про дерево {str(carried)[:12]}, а міряємо {source_digest[:12]}: "
            "це історичний доказ, не свіжий"
        ]
    return []


def problems(
    report: dict[str, Any], expected: set[str], source_digest: str | None = None
) -> list[str]:
    """Зауваження до звіту мутацій. `source_digest` — дайджест дерева, з яким звірятись.

    Параметр НЕ має дефолту-заглушки навмисно: `None` означає «звіряти нема з чим», і
    тоді прив'язка не перевіряється, а не вважається доброю. Виміряно 2026-09-06: доти
    перевірка питала лише, чи дайджест НЕПОРОЖНІЙ, тож звіт із шістдесятьма чотирма
    нулями проходив як свіжий. Назва цілі обіцяла свіжість, вимір давав присутність.
    """
    found: list[str] = binding_problems(report, source_digest)
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
    # Доти перевірялися лише ці три СПИСКИ, які звіт складає САМ ПРО СЕБЕ. Виміряно
    # 06.09.2026: звіт, де всі 624 рядки мають `status: "SURVIVED"`, `killed: 0` і
    # власний `status: "FAIL"`, але `survived: []`, проходив без жодного зауваження —
    # і тут, і в `verify_current_truth`. Гейт вірив підсумку замість того, щоб його
    # перерахувати. Нижче читаються самі результати: підсумок мусить збігатися з ними.
    outcomes: dict[str, int] = {}
    for row in results:
        if isinstance(row, dict):
            outcomes[str(row.get("status"))] = outcomes.get(str(row.get("status")), 0) + 1
    not_killed = {name: count for name, count in outcomes.items() if name != "KILLED"}
    if not_killed:
        found.append(f"результати містять невбитих мутантів: {not_killed} — підсумок їх не називає")
    declared_killed = report.get("killed")
    counted_killed = outcomes.get("KILLED", 0)
    if isinstance(declared_killed, int) and declared_killed != counted_killed:
        found.append(
            f"звіт оголошує killed={declared_killed}, а результатів KILLED {counted_killed}"
        )
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
        # НЕ "0" * 64: доти саме це число стояло тут як ЧИСТИЙ випадок, і клас вади
        # «звіт про інше дерево» був невидимий за побудовою — еталон оголошував отруту
        # правильним входом.
        "provenance": {"source_digest": "a" * 64},
        "survived": [],
        "invalid": [],
        "errors": [],
    }
    rows: list[dict[str, str]] = [{"id": "M01"}, {"id": "M02"}, {"id": "M03"}]
    cases: list[tuple[str, dict[str, Any], bool]] = [
        ("чистий стан приймається", good, False),
        # Дві отрути по ДАНИХ на прив'язку. Обидві проходили до 2026-09-06.
        (
            "звіт про ІНШЕ дерево не є свіжим",
            {**good, "provenance": {"source_digest": "b" * 64}},
            True,
        ),
        (
            "дайджест-заглушка не рятує звіт",
            {**good, "provenance": {"source_digest": "0" * 64}},
            True,
        ),
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
        # Дайджест еталона передається ЯВНО: без нього дві нові отрути на
        # прив'язку не мали б з чим звірятись і мовчки проходили б — тобто
        # негативний контроль існував би, не бігаючи.
        rejected = bool(problems(payload, expected, "a" * 64))
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
    found = problems(report, catalogue_ids(), compute_source_digest(ROOT))
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
