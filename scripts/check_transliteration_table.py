#!/usr/bin/env python3
"""Таблиця синонімів, складена з уяви, виглядає точно як складена з виміру.

Кожен запис існує лише тому, що латинська форма СПРАВДІ резолвиться в корпусі, а
українська — ні. Запис, чия латинська форма нічого не знаходить, додає синонім до
слова, якого немає: жодної шкоди у видачі, і повна ілюзія покриття в таблиці.

Виміряно 31.08.2026: п'ятнадцять названих систем існують у корпусі ЛИШЕ латиницею —
Stryker 335 прольотів, Bradley 192, Abrams 130, Javelin 113, Stinger 68, HIMARS 62.
Україномовне питання про них не знаходило нічого, і солдат робив із мовчання висновок
про корпус.

Гейт переміряє таблицю проти ТОГО САМОГО корпусу, який обслуговується. Без бази він
каже UNKNOWN і виходить з 2 — не з 1: «не зміг виміряти» не є «виміряв і відхилив».
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "config/corpus/transliteration.json"
DEFAULT_DB = ROOT / "var/runtime/corpus-v6-20260807/korpus.db"


def hits(connection: sqlite3.Connection, term: str) -> int:
    row = connection.execute(
        "select count(*) from evidence_fts where evidence_fts match ?", (f'"{term}"*',)
    ).fetchone()
    return int(row[0])


def problems(entries: list[dict[str, Any]], connection: sqlite3.Connection) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        ua, latin = str(entry.get("ua", "")), str(entry.get("latin", ""))
        if not ua or not latin:
            found.append(f"неповний запис: {entry!r}")
            continue
        if ua in seen:
            found.append(f"{ua!r}: дубльований запис — два різні відповідники неможливо розсудити")
        seen.add(ua)
        latin_hits, ua_hits = hits(connection, latin), hits(connection, ua)
        if latin_hits == 0:
            found.append(
                f"{ua!r} → {latin!r}: латинська форма не резолвиться в корпусі "
                "— синонім до слова, якого немає"
            )
        if ua_hits > 0:
            found.append(
                f"{ua!r}: українська форма вже резолвиться ({ua_hits}) — запис зайвий, "
                "а зайвий синонім розширює пошук без причини"
            )
    return found


def selftest() -> int:
    """Отрути по ДАНИХ: корпус у пам'яті, у якому відомо, що є і чого немає."""
    connection = sqlite3.connect(":memory:")
    connection.execute("create virtual table evidence_fts using fts5(text)")
    connection.executemany(
        "insert into evidence_fts(text) values (?)",
        [("The Javelin missile",), ("HIMARS battery",), ("Ланцет застосовується",)],
    )
    cases: list[tuple[str, list[dict[str, Any]], bool]] = [
        ("чистий стан", [{"ua": "джавелін", "latin": "javelin"}], False),
        ("латинської форми немає в корпусі", [{"ua": "вигадка", "latin": "nonexistent"}], True),
        ("українська форма вже резолвиться", [{"ua": "ланцет", "latin": "lancet"}], True),
        ("неповний запис", [{"ua": "джавелін"}], True),
        (
            "дубль",
            [{"ua": "джавелін", "latin": "javelin"}, {"ua": "джавелін", "latin": "himars"}],
            True,
        ),
    ]
    failures = [
        name
        for name, entries, must_reject in cases
        if bool(problems(entries, connection)) != must_reject
    ]
    print(json.dumps({"selftest": len(cases), "failed": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
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
    payload = json.loads(TABLE.read_text(encoding="utf-8"))
    connection = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    found = problems(list(payload.get("entries", [])), connection)
    print(
        json.dumps(
            {
                "status": "FAIL" if found else "PASS",
                "entries": len(payload.get("entries", [])),
                "problems": found,
            },
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
        print(
            json.dumps(
                {"status": "ERROR", "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False
            )
        )
        raise SystemExit(2) from error
