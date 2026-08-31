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
  span_source_fidelity  — частка прольотів, які є ДОСЛІВНИМ зрізом свого джерела. Ця вісь
                          з'явилась 31.08.2026, коли ремонт меж прольотів підняв наступну
                          вісь 0.1555 → 0.7424 ціною, якої вона не бачила: 23 689 із
                          38 863 (60,96 %) перестали бути підрядком джерела, а 9 389 швів
                          склеїли по дві літери в слова, яких у документі немає —
                          `stabilityttacks`, `andontact`, `Servicexperiencing`. Цитата, що
                          містить неіснуюче слово, спростовує саме твердження системи, тож
                          ця вісь стоїть ПЕРЕД тією, заради якої її зламали.
  span_sentence_start   — частка прольотів, що починаються на межі речення. Міряється
                          ТОЧНО: проліт відшукується в джерелі, і дивиться символ ПЕРЕД
                          ним. Попередня версія питала лише, чи перша літера велика —
                          сурогат, який завищував на 0.077 (0.7424 проти 0.6654) і
                          керувався формою: одна константа `MAX_SPAN_CHARS` 1400 → 1600
                          піднімала його на 0.20, не додавши жодного символу інформації, а
                          викидання 8,4 % корпусу давало той самий бал, що й акуратний
                          ремонт.

Обидві — про КОРПУС, не про конвеєр, тож жоден прогін питань їх не побачить. Вимір
робиться прямо по базі, яка обслуговується.
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


def span_quality(spans: list[tuple[str, str]], sources: dict[str, str]) -> dict[str, Any]:
    """Дві властивості одразу, бо поодинці кожну можна вдовольнити ціною іншої."""
    total = len(spans)
    if not total:
        return {"total": 0, "verbatim": 0, "sentence_start": 0, "rate": None}
    terminators = set('.!?…»"\u2019\u201d)')
    verbatim = boundary = first = unlocatable = 0
    previous_version = None
    cursor = 0
    for version_id, text in spans:
        if version_id != previous_version:
            previous_version, cursor = version_id, 0
        source = sources.get(version_id)
        if source is None:
            unlocatable += 1
            continue
        needle = " ".join(text.split())
        if not needle:
            unlocatable += 1
            continue
        if needle in source:
            verbatim += 1
        probe = needle[:80]
        at = source.find(probe, max(0, cursor - 2000))
        if at < 0:
            at = source.find(probe)
        if at < 0:
            unlocatable += 1
            continue
        cursor = at + len(needle)
        if at == 0:
            first += 1
            continue
        before = source[:at].rstrip()
        if before and before[-1] in terminators:
            boundary += 1
    return {
        "total": total,
        "verbatim": verbatim,
        "verbatim_rate": verbatim / total,
        "sentence_start": boundary + first,
        "first_in_version": first,
        # Проліт, якого немає в джерелі, не кредитується жодною з осей: «не знайшли» —
        # це не «в порядку».
        "unlocatable": unlocatable,
        "rate": (boundary + first) / total,
    }


def measure(database: Path, object_root: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    versions = [row[0] for row in connection.execute("select source_uri from document_versions")]
    sources: dict[str, str] = {}
    for version_id, object_key in connection.execute(
        "select id, object_key from document_versions"
    ):
        path = object_root / str(object_key)
        if path.is_file():
            sources[str(version_id)] = " ".join(
                path.read_text(encoding="utf-8", errors="replace").split()
            )
    spans = [
        (str(row[0]), str(row[1]))
        for row in connection.execute(
            "select version_id, text from evidence_spans order by version_id, ordinal"
        )
    ]
    return {
        "schema": "korpus.corpus-integrity.v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "database": str(database),
        "inputs": report_inputs(database, Path(__file__).resolve()),
        "inputs_digest": inputs_digest(report_inputs(database, Path(__file__).resolve())),
        "status": "MEASURED" if versions and spans else "UNKNOWN",
        "citation_traceability": traceability(versions),
        "span_sentence_start": span_quality(spans, sources),
        "span_source_fidelity": {
            "rate": span_quality(spans, sources)["verbatim_rate"] if spans else None
        },
        "cannot_judge": [
            "Чи веде глибоке посилання на ПРАВИЛЬНИЙ документ — тут міряється лише "
            "форма посилання, не його призначення.",
            "Крапка не завжди кінчає речення: скорочення, крапкові лідери змісту й "
            "десяткові числа зараховуються межею. Оцінено як завищення на 0.05–0.06.",
            "Проліт, що є дослівним зрізом джерела, не є через це ДОРЕЧНИМ зрізом: "
            "міряється тотожність тексту, не осмисленість межі.",
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
    source = {"v": "Перше речення тут. Друге речення тут. Третє речення тут."}
    span_cases: list[tuple[str, list[tuple[str, str]], str, Any]] = [
        ("проліт після крапки — межа", [("v", "Друге речення тут.")], "rate", 1.0),
        ("проліт посеред речення — не межа", [("v", "речення тут. Третє")], "rate", 0.0),
        ("перший проліт версії зараховується", [("v", "Перше речення тут.")], "rate", 1.0),
        ("дослівний зріз зараховується", [("v", "Друге речення тут.")], "verbatim_rate", 1.0),
        (
            "текст, якого в джерелі немає, НЕ дослівний",
            [("v", "Друге реченняТретє тут.")],
            "verbatim_rate",
            0.0,
        ),
        (
            "склеєні літери ловляться саме цією віссю",
            [("v", "Перше речення тут.Друге")],
            "verbatim_rate",
            0.0,
        ),
        ("джерела немає — не кредитується", [("нема", "будь-що")], "unlocatable", 1),
        ("порожній набір не має частки", [], "rate", None),
    ]
    failures += [
        f"{name}: {span_quality(items, source)[field]!r} != {want!r}"
        for name, items, field, want in span_cases
        if span_quality(items, source)[field] != want
    ]
    print(
        json.dumps(
            {"selftest": len(cases) + len(span_cases), "failed": failures},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--object-root", type=Path)
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
    object_root = args.object_root or args.database.parent / "objects"
    if not object_root.is_dir():
        # Без джерела дослівність не перевіряється взагалі, а частка над неперевіреним —
        # це не вимір.
        print(
            json.dumps({"status": "UNKNOWN", "reason": f"немає {object_root}"}, ensure_ascii=False)
        )
        return 2
    report = measure(args.database, object_root)
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
