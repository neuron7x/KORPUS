#!/usr/bin/env python3
"""Обстановка носія не сміє бути цитовною як доктрина.

Система обіцяє солдату те саме, чим сильна: кожне твердження — цитата з хешем і
посиланням. Обіцянка ламається не тоді, коли відповідь порожня, а тоді, коли в ролі
доказу приходить «Reset password» або `class="cmp-text"` — з тим самим хешем і тим
самим виглядом достовірності. Порожня відповідь видно; процитований cookie-банер — ні.

Виміряно 31.08.2026 на рантайм-корпусі: 31 проліт із 38 880 несе розмітку або хром
носія, і ВСІ 31 у стані `approved` + `is_current`, тобто цитовні просто зараз. 15 із
них — з однієї тематичної сторінки НАТО, ще два — з наказу Міноборони № 516.

Гейт дивиться лише на ЦИТОВНІ прольоти. Неприйнятий чи застарілий проліт може містити
що завгодно: він не потрапить у відповідь, і вимагати від нього чистоти означало б
міряти не те, що болить.

    validate_span_hygiene.py --database URL [--json]
    validate_span_hygiene.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

#: ЕКРАНОВАНА розмітка. `&lt;p>` або `&#34;` не є текстом документа НІКОЛИ й ні в
#: якій доктрині: це наслідок подвійного кодування — джерело віддало вже екрановану
#: розмітку, екстрактор розкодував один раз, і залишок осів у прольоті як «текст».
#:
#: Правило свідомо вужче за дві мої попередні спроби, і обидві варті запису. Перша
#: ловила будь-який тег або слово «cookies» — і позначила справжню доктрину НАТО
#: («does not seek confrontation») як сміття, бо збіг був десь у 300-символьному вікні,
#: а не в реченні. Друга міряла ЧАСТКУ сміття — і назвала чистим уламок `href`, а
#: брудним справжнє речення з одним префіксом `&lt;p>`. Обидві читали повз те, що
#: охороняли. Екранована розмітка такої двозначності не має.
ESCAPED_MARKUP = re.compile(r"&lt;/?[a-z]|&#34;|&quot;|&amp;nbsp;")
#: Обстановка носія: те, що належить сторінці, а не документу. Вужче нікуди — кожне
#: слово тут або службове (`cmp-`), або належить банеру згоди.
CHROME = re.compile(r"(?i)\bcmp-|reset password|\bcookies?\b|\bconsent banner\b")

QUERY = (
    "SELECT s.id, d.canonical_title, replace(left(s.text, 300), chr(10), ' ') "
    "FROM evidence_spans s "
    "JOIN document_versions v ON v.id = s.version_id "
    "JOIN documents d ON d.id = v.document_id "
    "WHERE v.review_state = 'approved' AND v.is_current"
)


def dirty(text: str) -> str | None:
    if ESCAPED_MARKUP.search(text):
        return "escaped_markup"
    if CHROME.search(text):
        return "chrome"
    return None


def scan(rows: list[tuple[str, str, str]]) -> dict[str, object]:
    findings = [(sid, title, text, kind) for sid, title, text in rows if (kind := dirty(text))]
    return {
        "schema": "korpus.span-hygiene.v1",
        "spans_citable": len(rows),
        "spans_dirty": len(findings),
        "by_kind": dict(Counter(k for *_, k in findings)),
        "by_document": dict(Counter(t[:70] for _, t, _, _ in findings).most_common(10)),
        "examples": [t[:120] for _, _, t, _ in findings[:3]],
        "status": "PASS" if not findings else "FAIL",
    }


def _rows_from(database: str) -> list[tuple[str, str, str]]:
    import subprocess

    result = subprocess.run(
        ["psql", database, "-tAc", QUERY], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"psql відмовив: {result.stderr.strip()[:200]}")
    rows: list[tuple[str, str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 3:
            rows.append((parts[0], parts[1], "|".join(parts[2:])))
    if not rows:
        raise SystemExit("жодного цитовного прольоту — це відмова, а не чистий корпус")
    return rows


def selftest() -> int:
    """Отрути по ДАНИХ: правило мусить ловити хром і мовчати на справжньому тексті."""
    cases = [
        ("справжня доктрина", "Командир бригади відповідає за бойову готовність.", None),
        ("посилання в реченні", "Available at https://armypubs.army.mil/epubs/DR_pubs.", None),
        ("сутність у тексті", "Звіти Центру протидії дезінформації&#8230; за 2026 рік.", None),
        (
            "доктрина НАТО, яку я двічі позначила хибно",
            "NATO does not seek confrontation and poses no threat to Russia.",
            None,
        ),
        ("cookie-банер", "We use cookies to understand additional site usage.", "chrome"),
        ("скидання пароля", 'class="cmp-text"> Reset password', "chrome"),
        (
            "екранований тег",
            'ml">supported the finding&lt;/a>&amp;nbsp;that Russia',
            "escaped_markup",
        ),
        ("екранована лапка", "&#34;}} id=text-ddd6 Access NATO", "escaped_markup"),
    ]
    ok = 0
    for name, text, want in cases:
        got = dirty(text)
        good = got == want
        ok += good
        print(f"  {'ok' if good else 'ПРОВАЛ'} {name}: {got!r} (мало бути {want!r})")
    empty = scan([])
    print(f"  {'ok' if empty['status'] == 'PASS' else 'ПРОВАЛ'} порожній вхід не падає у FAIL")
    print(f"негативний контроль: {ok}/{len(cases)}")
    return 0 if ok == len(cases) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    if not arguments.database:
        parser.error("потрібен --database")
    report = scan(_rows_from(arguments.database))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
