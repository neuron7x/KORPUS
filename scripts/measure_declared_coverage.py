#!/usr/bin/env python3
"""Чого корпусу бракує проти того, що система про себе ОГОЛОСИЛА.

Два найбільші відкриті борги — «у корпусі немає джерела» і «тактична медицина майже
відсутня» — знайдені ВИПАДКОВО, під час гонитви за іншим числом. Не існувало інструмента,
який сказав би це сам, тож розрив між оголошеним і наявним лишався невидимим, доки хтось
не спіткнувся об нього.

`boundary_own` питає СИСТЕМУ: скільки своїх питань вона ще тягне (0.95). Це вимір
конвеєра. Тут питання інше й до КОРПУСУ: чи є в ньому матеріал, на якому взагалі можна
відповісти. Система, що відповідає на 0.95 своїх питань, і корпус, у якому «артеріальн»
трапляється нуль разів, — сумісні стани, і другий пояснює перший.

**Оголошення береться з дерева, не вигадується.** Набори `domain_boundary.jsonl`
(питання, позначені як СВОЇ) і `reference.jsonl` заморожені з дайджестами: це те, що
система про себе стверджує. Таксономія, яку я склав би сам, була б моєю думкою про її
призначення.

**Сигнал.** Для кожного питання береться найрідший його змістовний термін: скільки разів
він трапляється в корпусі. Нуль означає, що питання оголошене й спертись на корпус
неможливо. Виміряно 31.08.2026: «артеріальній» 0, «пораненні» 0, «турнікет» 4, «джгут» 4
— проти контрольних «командир» 4465, «варт» 1644.

**Чого цей вимір НЕ каже.** Він лексичний. Питання, на яке корпус відповідає іншими
словами, тут виглядає непокритим; питання, чиї слова є, але не про те, — покритим. Тому
це інструмент пріоритету для інжесту, а не вирок про якість відповіді: вирок виносять осі
відповіді, кожна на своєму наборі.

## Наявність терміна ≠ можливість діяти

Виміряно 01.09.2026, і воно спростовує попередній запис ЦЬОГО файла. «Тактична медицина
українською майже відсутня» — надто сильно: корпус тримає два українські документи про
неї. Але обидва — документи ПРО предмет, не документи предмета: наказ, що перелічує
НАЗВИ втручань («Використання турнікета для зупинки кровотечі»), і силабус навчальної
дисципліни («слухачі повинні знати», «удосконалення знань»). Ні там, ні там немає, ЯК.

Тому додано другий сигнал: чи бодай один проліт, що містить найрідший термін питання,
несе ДИРЕКТИВНУ форму — закритий набір нормативних зворотів («зобов’язаний», «повинен»,
«необхідно», «забороняється», «накладається», «здійснюється»…).

Контроль вбудований і без нього число нічого не варте:
  по корпусу загалом    1745 із 31 464 прольотів = 0.055
  «чатов»               52 із 99   = 0.53
  «наказ»               218 із 522 = 0.42
  «варт»                159 із 440 = 0.36
  «турнікет»            0 із 2     «джгут» 0 із 4    «артеріальн» 0 із 2
  «пневмоторакс»        0 із 5     «кровотеч» 1 із 13
Службова частина корпусу вшестеро-вдесятеро над базовим рівнем; медична — на ньому або
під ним. Отже детектор розділяє, і розділяє не мову, а рід тексту.

`directive_baseline` друкується у звіті НАВМИСНО: послаблений набір зворотів підняв би
«придатність», і єдине, що це видно — базовий рівень, який поїхав угору разом із нею.

    measure_declared_coverage.py --database DB [--out ФАЙЛ]
    measure_declared_coverage.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus_identity import inputs_digest, report_inputs  # noqa: E402

DEFAULT_DB = ROOT / "var/runtime/corpus-v6-20260807/korpus.db"
DECLARED = (
    ROOT / "evals/datasets/domain_boundary.jsonl",
    ROOT / "evals/datasets/reference.jsonl",
)
_WORD = re.compile(r"[а-яіїєґa-z0-9']{4,}")
#: Службові слова питання не несуть предмета, тож їхня частота нічого не каже про корпус.
STOP = frozenset(
    [
        "як",
        "що",
        "чи",
        "для",
        "при",
        "або",
        "та",
        "і",
        "в",
        "у",
        "на",
        "з",
        "до",
        "по",
        "не",
        "від",
        "про",
        "який",
        "яка",
        "яке",
        "скільки",
        "де",
        "коли",
        "хто",
        "чому",
        "цього",
        "того",
        "цьому",
        "яких",
        "яким",
        "котрий",
        "після",
        "перед",
        "між",
    ]
)
#: Нижче цього корпус не тримає предмет, а лише згадує його. Число не кругле й не з
#: доктрини: це медіана найрідшого терміна серед питань, на які система відповідає, за
#: виміром 31.08.2026 — нижче нього починаються ті, де вона мовчить або промахується.
THIN_BELOW = 10


#: Закритий набір директивних зворотів українського нормативного тексту. Закритий, бо
#: відкритий список — це регулятор, яким «придатність» підкручується до бажаного числа.
DIRECTIVE = re.compile(
    r"(зобов['’]язаний|зобов['’]язані|повинен|повинна|повинні|необхідно|слід\s|"
    r"забороняється|не\s+дозволяється|дозволяється|накладається|здійснюється|"
    r"проводиться|виконується|застосовується|вживає|вживають)",
    re.IGNORECASE,
)


def content_terms(question: str) -> list[str]:
    return [word for word in _WORD.findall(question.lower()) if word not in STOP]


def support(terms: list[str], corpus: str) -> tuple[int, list[tuple[str, int]]]:
    """Скільки разів трапляється найрідший термін, і скільки — кожен."""
    counts = [(term, corpus.count(term)) for term in terms]
    return (min(count for _, count in counts) if counts else 0), counts


def declared_questions(paths: tuple[Path, ...]) -> list[dict[str, Any]]:
    """Питання, які система оголосила СВОЇМИ. Чуже сюди не потрапляє за побудовою."""
    out: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            identifier = str(case.get("id", ""))
            # Оголошеним вважається лише те, на що система БЕРЕТЬСЯ відповідати.
            # Набір містить випадки, де правильна поведінка — ВІДМОВА: `kind` refusal
            # і adversarial, `expect` abstained і blocked_or_abstained, та питання з
            # префіксом `out`. Перша версія цього виміру рахувала їх прогалинами
            # покриття, і серед «непокритих» опинились рядки з випадкових літер —
            # тобто вимір вимагав від корпусу матеріалу на те, що він мусить відхиляти.
            if identifier.startswith("out"):
                continue
            if str(case.get("kind", "")) in {"refusal", "adversarial"}:
                continue
            if str(case.get("expect", "")) in {"abstained", "blocked_or_abstained"}:
                continue
            question = case.get("question") or case.get("query") or case.get("text")
            if question:
                # Питання, ВИБРАНЕ з корпусу, має підтримку за побудовою: міряти її —
                # майже коло. Осмислений вимір лише на рукописних твердженнях про
                # домен; вибране лишається окремо, де нуль означає не прогалину
                # покриття, а дефект витягу.
                out.append(
                    {
                        "id": identifier,
                        "question": str(question),
                        "set": path.name,
                        "sampled": bool(case.get("sampled_from_version")),
                    }
                )
    return out


def actionable(term: str, spans: list[str]) -> tuple[int, int]:
    """Скільки прольотів містять термін і скільки з них ГОВОРЯТЬ, що робити."""
    holding = [span for span in spans if term in span]
    return len(holding), sum(1 for span in holding if DIRECTIVE.search(span))


def classify(case: dict[str, Any], corpus: str, spans: list[str]) -> dict[str, Any] | None:
    """Одне оголошення: чи термін є, і чи бодай один його проліт КАЖЕ, що робити."""
    terms = content_terms(case["question"])
    if not terms:
        return None
    weakest, counts = support(terms, corpus)
    rarest = min(counts, key=lambda pair: pair[1])[0]
    holding, directive = actionable(rarest, spans) if weakest else (0, 0)
    return {
        **case,
        "min_support": weakest,
        "absent_terms": sorted(term for term, count in counts if count == 0)[:4],
        "rarest_term": rarest,
        "spans_holding_rarest": holding,
        "spans_with_directive": directive,
    }


def sort_into_buckets(
    questions: list[dict[str, Any]], corpus: str, spans: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Чотири купки: без підстави, лише названі, придатні, тонкі.

    «Лише названий» і «придатний» — не два ступені однієї шкали: перше означає, що
    корпус говорить ПРО предмет, друге — що він говорить предметом. Читач може діяти
    лише за другим.
    """
    buckets: dict[str, list[dict[str, Any]]] = {
        "unsupported": [],
        "named_only": [],
        "actionable": [],
        "thin": [],
    }
    for case in questions:
        record = classify(case, corpus, spans)
        if record is None:
            continue
        if record["min_support"] == 0:
            buckets["unsupported"].append(record)
            continue
        buckets["actionable" if record["spans_with_directive"] else "named_only"].append(record)
        if record["min_support"] < THIN_BELOW:
            buckets["thin"].append(record)
    return buckets


def measure(database: Path, paths: tuple[Path, ...]) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    spans = [text.lower() for (text,) in connection.execute("select text from evidence_spans")]
    connection.close()
    corpus = " ".join(spans)
    # Базовий рівень рахується на ВСЬОМУ корпусі й друкується у звіті: без нього
    # «придатність» підкручується послабленням набору зворотів, і ніхто не побачить.
    baseline = sum(1 for span in spans if DIRECTIVE.search(span))
    every = declared_questions(paths)
    questions = [case for case in every if not case["sampled"]]
    sampled = [case for case in every if case["sampled"]]
    sampled_absent = [
        case
        for case in sampled
        if content_terms(case["question"])
        and support(content_terms(case["question"]), corpus)[0] == 0
    ]
    buckets = sort_into_buckets(questions, corpus, spans)
    unsupported = buckets["unsupported"]
    thin = buckets["thin"]
    actionable_cases = buckets["actionable"]
    named_only = buckets["named_only"]
    total = len(questions)
    return {
        "schema": "korpus.declared-coverage.v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "database": str(database),
        "declared_questions": total,
        "sampled_questions": len(sampled),
        # Нуль тут — не прогалина покриття, а дефект витягу: питання вибране з корпусу,
        # тож його слова мусять у ньому бути.
        "sampled_without_support": len(sampled_absent),
        "unsupported": len(unsupported),
        "thin": len(thin),
        "rate": ((total - len(unsupported)) / total) if total else None,
        # Наявність терміна ≠ можливість діяти. Наказ, що перелічує НАЗВИ втручань, і
        # силабус навчальної дисципліни дають повну наявність і нульову придатність.
        "actionable": len(actionable_cases),
        "named_only": len(named_only),
        "actionable_rate": (len(actionable_cases) / total) if total else None,
        "directive_baseline": round(baseline / len(spans), 4) if spans else None,
        "named_only_examples": named_only[:8],
        "unsupported_examples": unsupported[:12],
        "thin_examples": thin[:8],
        "status": "MEASURED" if total else "UNKNOWN",
        "cannot_judge": [
            "Вимір лексичний: питання, на яке корпус відповідає ІНШИМИ словами, тут "
            "виглядає непокритим, а питання, чиї слова є, але не про те, — покритим.",
            "Це пріоритет для інжесту, не вирок про якість відповіді: вирок виносять осі "
            "відповіді, кожна на своєму наборі.",
            "Директивна форма — ознака РОДУ тексту, не його правильності: проліт, що каже "
            "робити не те, тут виглядає придатним. Розділяє він норму від опису норми, і "
            "більше нічого.",
        ],
    }


def selftest() -> int:
    corpus = "командир віддає наказ вартовому. варта несе службу згідно зі статутом."
    cases = [
        ("термін, якого в корпусі немає", ["турнікет"], 0),
        ("термін, який є", ["командир"], 1),
        ("найрідший вирішує", ["командир", "турнікет"], 0),
        ("порожній перелік не дає підтримки", [], 0),
    ]
    failures = [
        f"{name}: {support(terms, corpus)[0]}"
        for name, terms, want in cases
        if support(terms, corpus)[0] != want
    ]
    if content_terms("Як накласти турнікет пораненому?") != ["накласти", "турнікет", "пораненому"]:
        failures.append("службові слова не відкинуто")
    if declared_questions((ROOT / "evals/datasets/domain_boundary.jsonl",)) and any(
        case["id"].startswith("out")
        for case in declared_questions((ROOT / "evals/datasets/domain_boundary.jsonl",))
    ):
        failures.append("чуже питання потрапило в оголошені")
    print(
        json.dumps({"selftest": len(cases) + 2, "failed": failures}, ensure_ascii=False, indent=2)
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=ROOT / "var/declared-coverage.json")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.database.is_file():
        print(
            json.dumps(
                {"status": "UNKNOWN", "reason": f"немає {args.database}"}, ensure_ascii=False
            )
        )
        return 2
    report = measure(args.database, DECLARED)
    measurer = Path(__file__).resolve()
    report["inputs"] = report_inputs(args.database, measurer)
    report["inputs_digest"] = inputs_digest(report["inputs"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "MEASURED" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:
        print(
            json.dumps(
                {"status": "ERROR", "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False
            )
        )
        raise SystemExit(2) from error
