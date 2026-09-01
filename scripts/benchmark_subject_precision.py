#!/usr/bin/env python3
"""Чи відповідь про того, кого спитали.

Система вміє довести, що цитата справжня: хеш фрагмента, зміщення, посилання на
першоджерело. Вона НЕ вміє показати, що цитата стосується предмета питання, — і це
різні твердження. Виміряно 31.08.2026: на 101 питання «Які обов'язки має X?» перша
цитата ЖОДНОГО разу не була документом про X. Нуль зі ста одного.

Питання беруться не з голови: корпус сам оголошує свої предмети заголовками виду
`Обов'язки: <роль> (Статут, ст.N)`. Тому набір закритий, правильна відповідь відома
до прогону, і бенчмарк не можна підігнати переформулюванням — він рівно про те, чи
конвеєр знаходить документ, який САМ СЕБЕ оголосив відповіддю.

ЩО ЩЕ МІРЯЄТЬСЯ, І ЧОМУ ЦЕ ГОЛОВНЕ. Окремо рахується впевненість на правильних і на
хибних відповідях. Якщо система звітує ВИЩЕ покриття там, де помилилась, — сигнал
не просто неінформативний, він перевернутий, і кожне «coverage 1.0» на екрані читача
означає протилежне тому, що обіцяє. Перший вимір дав саме це: 1.0 на хибних проти
0.8 на правильній.

ДРУГА ФОРМА, і без неї перше число неповне. Еталон питає НАЗИВНИМ, бо роль береться із
заголовка як є; людина питає РОДОВИМ. Виміряно 01.09.2026 на живому продукті:
називний 14/14, родовий **1/14**. Отже 0.9670 — правда про розподіл входу «називний», і
про форму, яку справді введе читач, воно не каже нічого. Відмінені форми лежать
замороженим набором (`evals/datasets/subject_inflection.jsonl`), кожна прогнана на
сервері до внесення: автоматично утворити родовий для 92 українських ролей надійно не
можна, а утворене без перевірки було б думкою про мову, покладеною в еталон.

    benchmark_subject_precision.py --base http://127.0.0.1:8000 --database DB
    benchmark_subject_precision.py --base ... --inflected
    benchmark_subject_precision.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: Правило розбору заголовка вписане ТУТ, а не імпортоване з конвеєра, і це навмисно.
#: Лінійка, що ділить код із тим, що міряє, перестає бути незалежною: зміна визначення
#: предмета в конвеєрі тихо змінила б і те, як бенчмарк рахує правильну відповідь, — і
#: число лишилося б високим саме тоді, коли поведінка змінилась. Дублювання ЗНАЧЕННЯМ
#: тут дешевше за спільну залежність: розбіжність між двома визначеннями має бути
#: видимою як розбіжність чисел, а не схованою в спільній функції.
DECLARED_SUBJECT = re.compile(r"^Обов[’']язки:\s*(?P<subject>.+?)\s*\(")
MIN_SUBJECT_CHARS = 8

TITLE_SHAPE = "Обов%язки:%"


def declared_subject(title: str) -> str | None:
    matched = DECLARED_SUBJECT.match(title)
    if matched is None:
        return None
    subject = matched.group("subject").strip()
    return subject if len(subject) >= MIN_SUBJECT_CHARS else None


#: Формулювання навмисно різні: якби бенчмарк питав рівно словами заголовка, він міряв
#: би збіг рядків, а не пошук. Усі чотири називають роль — і цього досить, бо предмет
#: оголошений, а не вгаданий.
PHRASINGS = (
    "Які обов'язки має {role}?",
    "Що зобов'язаний робити {role}?",
    "За що відповідає {role}?",
    "{role} — обов'язки",
)


INFLECTION_SET = ROOT / "evals/datasets/subject_inflection.jsonl"


def inflection_pairs(path: Path) -> list[dict[str, Any]]:
    """Відмінені форми з дерева, не утворені на льоту.

    Морфологія тут — ДАНІ, і навмисно. Правило, яке утворювало б родовий із називного,
    було б моєю думкою про українську мову всередині вимірювача, і його помилка
    виглядала б як властивість системи.
    """
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def cited_first_is(answer: dict[str, Any] | None, role: str) -> bool:
    """Перша цитата — документ, що ОГОЛОСИВ саме цю роль. Не схожість, а заголовок.

    Апостроф у заголовках трапляється двома символами, тож обидва зводяться до одного
    перед порівнянням: інакше правильна відповідь читалась би як хибна через кодування.
    """
    if answer is None:
        return False
    cited = [str(citation.get("title", "")) for citation in answer.get("citations", ())]
    if not cited:
        return False
    # Рівність оголошеного предмета, не префікс заголовка. Префікс зараховував би
    # «Обов'язки: Днювальний парку ТА СКЛАДУ» за «Днювальний парку»: роль — підрядок
    # довшої ролі, і саме так виглядала б хибно висока цифра. Розбір той самий, що вище
    # в цьому файлі, і навмисно НЕ імпортований із конвеєра.
    return declared_subject(cited[0]) == role


def _inflection_result(
    arguments: argparse.Namespace, pair: dict[str, Any]
) -> dict[str, Any] | None:
    """Одна роль у двох відмінках. None означає НЕДОСЯЖНО, а не промах."""
    role = str(pair["role"])
    nominative = ask(
        arguments.base, arguments.token, f"Які обов'язки має {role.lower()}?", arguments.timeout
    )
    genitive = ask(
        arguments.base, arguments.token, f"Які обов'язки {pair['genitive']}?", arguments.timeout
    )
    if nominative is None or genitive is None:
        return None
    return {
        "id": pair.get("id"),
        "role": role,
        "adjectival": bool(pair.get("adjectival")),
        "nominative": cited_first_is(nominative, role),
        "genitive": cited_first_is(genitive, role),
    }


def summarise_inflection(results: list[dict[str, Any]], unreachable: int) -> dict[str, Any]:
    total = len(results)
    nominative_ok = sum(1 for item in results if item["nominative"])
    genitive_ok = sum(1 for item in results if item["genitive"])
    return {
        "schema": "korpus.subject-inflection.v1",
        "cases": total,
        "unreachable": unreachable,
        "nominative": round(nominative_ok / total, 4) if total else None,
        "genitive": round(genitive_ok / total, 4) if total else None,
        #: Частка класу предмета, що ПЕРЕЖИВАЄ відмінювання. Відношення подібного до
        #: подібного, а не сира частка: якщо колись просяде сам називний, ця вісь не
        #: зросте від того, що обидві форми стали однаково поганими.
        "survives_inflection": (round(genitive_ok / nominative_ok, 4) if nominative_ok else None),
        #: Стеля 12/14 — межа МЕТОДУ, не борг: дві пари не зводяться відрізанням
        #: суфікса в принципі (випадний голосний, чергування основи).
        "ceiling": round(12 / total, 4) if total else None,
        "failed_in_genitive": [item["role"] for item in results if not item["genitive"]],
        "status": "MEASURED" if total else "UNKNOWN",
    }


def run_inflected(arguments: argparse.Namespace) -> int:
    """Те саме питання у двох відмінках; різниця між ними і є вимір."""
    pairs = inflection_pairs(arguments.inflection_set)
    if not pairs:
        raise SystemExit("набір відмінків порожній — це відмова, а не результат")
    results: list[dict[str, Any]] = []
    unreachable = 0
    for pair in pairs:
        result = _inflection_result(arguments, pair)
        if result is None:
            unreachable += 1
        else:
            results.append(result)
    report = {
        **summarise_inflection(results, unreachable),
        "base": arguments.base,
        "set": str(arguments.inflection_set.relative_to(ROOT)),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "failed_in_genitive"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def corpus_subjects(database: str) -> dict[str, str]:
    """роль -> заголовок, з корпусу, а не з переліку в коді."""
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT d.canonical_title FROM documents d"
            " JOIN document_versions v ON v.document_id = d.id"
            " AND v.is_current = 1 AND v.review_state = 'approved'"
            " WHERE d.canonical_title LIKE ?",
            (TITLE_SHAPE,),
        ).fetchall()
    finally:
        connection.close()
    subjects: dict[str, str] = {}
    for (title,) in rows:
        subject = declared_subject(title)
        if subject:
            subjects[subject] = title
    return subjects


def ask(base: str, token: str, question: str, timeout: float) -> dict[str, Any] | None:
    request = urllib.request.Request(
        f"{base.rstrip('/')}/v1/answers",
        data=json.dumps({"text": question, "locale": "uk"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
        | ({"Authorization": f"Bearer {token}"} if token else {}),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload: dict[str, Any] = json.loads(response.read())
            return payload
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def judge(answer: dict[str, Any], title: str) -> dict[str, Any]:
    """Вирок по одній відповіді. Правильність — за ЗАГОЛОВКОМ, не за схожістю тексту."""
    cited = [citation.get("title", "") for citation in answer.get("citations", ())]
    return {
        "status": answer.get("status"),
        "top_is_subject": bool(cited) and cited[0] == title,
        "any_is_subject": title in cited,
        "citations": len(cited),
        "query_coverage": answer.get("query_coverage"),
        "cited_first": cited[0][:70] if cited else None,
    }


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    answered = [r for r in results if r["status"] == "answered"]
    top = [r for r in answered if r["top_is_subject"]]
    anywhere = [r for r in answered if r["any_is_subject"]]

    def mean_coverage(items: list[dict[str, Any]]) -> float | None:
        values = [
            r["query_coverage"] for r in items if isinstance(r["query_coverage"], int | float)
        ]
        return round(statistics.fmean(values), 4) if values else None

    right_coverage = mean_coverage(anywhere)
    wrong_coverage = mean_coverage([r for r in answered if not r["any_is_subject"]])
    inverted = (
        right_coverage is not None
        and wrong_coverage is not None
        and wrong_coverage > right_coverage
    )
    return {
        "questions": len(results),
        "answered": len(answered),
        "top1_subject_precision": round(len(top) / len(answered), 4) if answered else None,
        "any_citation_subject_recall": round(len(anywhere) / len(answered), 4)
        if answered
        else None,
        "mean_coverage_when_right": right_coverage,
        "mean_coverage_when_wrong": wrong_coverage,
        #: Найважчий рядок звіту. True означає, що система звітує БІЛЬШУ впевненість
        #: саме тоді, коли помиляється, — і жоден інший показник цього не покаже.
        "confidence_inverted": inverted,
    }


def selftest() -> int:
    """Негативні контролі: бенчмарк мусить розрізняти оракула, саботажника й випадок."""
    title = "Обов'язки: Головний сержант роти (Статут, ст.1)"
    other = "Дисциплінарний статут Збройних Сил України"
    checks: list[tuple[str, Any, Any]] = []

    oracle = [{"citations": [{"title": title}], "status": "answered", "query_coverage": 0.4}]
    saboteur = [{"citations": [{"title": other}], "status": "answered", "query_coverage": 1.0}]

    judged_oracle = [judge(a, title) for a in oracle]
    judged_saboteur = [judge(a, title) for a in saboteur]
    checks.append(
        ("оракул дає точність 1.0", summarise(judged_oracle)["top1_subject_precision"], 1.0)
    )
    checks.append(("саботажник дає 0.0", summarise(judged_saboteur)["top1_subject_precision"], 0.0))
    checks.append(
        (
            "порожня відповідь не рахується правильною",
            judge({"citations": []}, title)["top_is_subject"],
            False,
        )
    )
    checks.append(
        (
            "цитата не першою — не top1, але зарахована в recall",
            (
                judge({"citations": [{"title": other}, {"title": title}]}, title)["top_is_subject"],
                judge({"citations": [{"title": other}, {"title": title}]}, title)["any_is_subject"],
            ),
            (False, True),
        )
    )
    mixed = judged_oracle + judged_saboteur
    checks.append(("перевернуту впевненість видно", summarise(mixed)["confidence_inverted"], True))
    straight = [
        judge(
            {"citations": [{"title": title}], "status": "answered", "query_coverage": 0.9}, title
        ),
        judge(
            {"citations": [{"title": other}], "status": "answered", "query_coverage": 0.2}, title
        ),
    ]
    checks.append(
        (
            "правильна впевненість НЕ позначається перевернутою",
            summarise(straight)["confidence_inverted"],
            False,
        )
    )

    passed = 0
    for name, got, want in checks:
        ok = got == want
        passed += ok
        print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: {got!r}")
    print(f"негативний контроль: {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--database")
    parser.add_argument("--phrasing", type=int, default=0, help="індекс формулювання, 0..3")
    parser.add_argument("--limit", type=int, default=0, help="0 = усі оголошені предмети")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--out", type=Path, default=ROOT / "var/subject-precision.json")
    parser.add_argument(
        "--inflected",
        action="store_true",
        help="друга форма: кожна роль питається називним І родовим із замороженого набору",
    )
    parser.add_argument("--inflection-set", type=Path, default=INFLECTION_SET)
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    # Друга форма читає ЗАМОРОЖЕНИЙ набір, не корпус, тож бази їй не треба. Перевірка
    # на `--database` стоїть нижче саме тому: вимога, яка не потрібна цій дорозі,
    # відхиляла б правильний виклик.
    if arguments.inflected:
        return run_inflected(arguments)

    if not arguments.database:
        parser.error("потрібен --database")

    subjects = corpus_subjects(arguments.database)
    if not subjects:
        raise SystemExit("корпус не оголошує жодного предмета — це відмова, а не результат")
    template = PHRASINGS[arguments.phrasing % len(PHRASINGS)]
    roles = sorted(subjects)[: arguments.limit or None]

    results: list[dict[str, Any]] = []
    unreachable = 0
    for role in roles:
        answer = ask(
            arguments.base, arguments.token, template.format(role=role.lower()), arguments.timeout
        )
        if answer is None:
            unreachable += 1
            continue
        results.append({"role": role, **judge(answer, subjects[role])})

    report = {
        "schema": "korpus.subject-precision.v1",
        "base": arguments.base,
        "phrasing": template,
        "declared_subjects": len(subjects),
        "unreachable": unreachable,
        **summarise(results),
        "worst": [
            {"role": r["role"], "cited_first": r["cited_first"], "coverage": r["query_coverage"]}
            for r in results
            if not r["any_is_subject"]
        ][:8],
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps({k: v for k, v in report.items() if k != "worst"}, ensure_ascii=False, indent=2)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
