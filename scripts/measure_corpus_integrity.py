#!/usr/bin/env python3
"""Дві властивості САМОГО корпусу, від яких залежить головне твердження системи.

«Знайти затверджене джерело, показати, ДЕ САМЕ це написано» — так описана ціннісна
функція. Перша половина міряється чотирма осями відповіді. Друга не міряється ніде, і
саме тому вона й виявилась найслабшою, щойно її поміряли:

  citation_traceability — частка версій, чиє посилання веде на КОНКРЕТНИЙ документ, а
                          не на голий домен. Виміряно 31.08.2026: 148 із 256 (57.8 %);
                          107 версій указують на `https://zakon.rada.gov.ua/` — титульну
                          сторінку порталу. Читач бачить кнопку «Відкрити точний
                          фрагмент», назву статуту й хеш — і посилання на головну.
  span_sentence_start   — частка прольотів, що починаються на межі речення. 32 820 із
                          38 863 (84,5 %) починаються посеред. Це властивість нарізки
                          корпусу, а не подання: подання вже позначає уривок, але сам
                          проліт лишається шматком фіксованого розміру.

Обидві — про КОРПУС, не про конвеєр, тож жоден прогін питань їх не побачить. Вимір
робиться прямо по базі, яка обслуговується.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "var/runtime/corpus-v6-20260807/korpus.db"
#: Голий домен: схема, хост і, найбільше, скісна. Усе інше — шлях до документа.
_BARE_DOMAIN = re.compile(r"https?://[^/]+/?$")


def traceability(rows: list[str | None]) -> dict[str, Any]:
    total = len(rows)
    if not total:
        return {"total": 0, "deep": 0, "bare": 0, "missing": 0, "rate": None}
    missing = sum(1 for value in rows if not value or not value.strip())
    bare = sum(1 for value in rows if value and _BARE_DOMAIN.fullmatch(value.strip()))
    deep = total - bare - missing
    return {
        "total": total,
        "deep": deep,
        "bare": bare,
        "missing": missing,
        # None, не 0.0, коли рахувати нема чого: частка над порожнім — відсутність виміру.
        "rate": deep / total,
    }


def sentence_starts(texts: list[str]) -> dict[str, Any]:
    total = len(texts)
    if not total:
        return {"total": 0, "whole": 0, "rate": None}
    mid = 0
    for text in texts:
        stripped = text.lstrip()
        if stripped and stripped[0].isalpha() and stripped[0].islower():
            mid += 1
    return {
        "total": total,
        "whole": total - mid,
        "mid_sentence": mid,
        "rate": (total - mid) / total,
    }


def measure(database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    versions = [row[0] for row in connection.execute("select source_uri from document_versions")]
    spans = [row[0] for row in connection.execute("select text from evidence_spans")]
    return {
        "schema": "korpus.corpus-integrity.v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "database": str(database),
        "status": "MEASURED" if versions and spans else "UNKNOWN",
        "citation_traceability": traceability(versions),
        "span_sentence_start": sentence_starts(spans),
        "cannot_judge": [
            "Чи веде глибоке посилання на ПРАВИЛЬНИЙ документ — тут міряється лише "
            "форма посилання, не його призначення.",
            "Проліт, що починається з великої літери, міг однаково бути обрізаний "
            "посередині — вимір ловить найчастіший випадок, не всі.",
        ],
    }


def selftest() -> int:
    cases: list[tuple[str, list[str | None], float | None]] = [
        ("усі глибокі", ["https://a.gov/doc/1", "https://b.gov/x"], 1.0),
        ("усі голі", ["https://a.gov/", "https://b.gov"], 0.0),
        ("порожні не зараховуються глибокими", [None, ""], 0.0),
        ("порожній набір не має частки", [], None),
    ]
    failures = [
        f"{name}: {traceability(rows)['rate']}"
        for name, rows, want in cases
        if traceability(rows)["rate"] != want
    ]
    spans = [("ціле речення", ["Речення."], 1.0), ("посеред", ["ня рани"], 0.0)]
    failures += [
        f"{name}: {sentence_starts(texts)['rate']}"
        for name, texts, want in spans
        if sentence_starts(texts)["rate"] != want
    ]
    print(
        json.dumps(
            {"selftest": len(cases) + len(spans), "failed": failures}, ensure_ascii=False, indent=2
        )
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=ROOT / "var/corpus-integrity.json")
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
    report = measure(args.database)
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
