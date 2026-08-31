#!/usr/bin/env python3
"""Прибрати з уже збережених прольотів розмітку, яка осіла в них як текст документа.

Причину усунено в екстракції: подвійно закодована розмітка тепер переparсюється, а не
лишається `&lt;p>`. Але фікс діє на НОВІ прольоти. Ті, що вже лежать у корпусі, який
подає сайт, лишаються такими, якими їх зберегли, — і саме їх солдат може отримати як
доказ, із хешем і посиланням.

Виміряно 31.08.2026 на `var/runtime/corpus-v6-20260807/korpus.db`: 98 цитовних прольотів
із 38 863 несуть екрановану розмітку або обстановку носія, у 23 версіях документів —
зокрема у Стройовому статуті ЗСУ й наказах Міноборони.

Ремонт — той самий `_strip_html`, що виправлено в екстракції: проліт переparсюється,
і `NON_DOCUMENT_ELEMENTS` діє на нього так само, як діяв би при першому розборі. Хеш
перераховується, бо він є `sha256` тексту й мусить описувати те, що справді лежить.

ЧОГО СКРИПТ НЕ РОБИТЬ. Не чіпає проліт, який після ремонту порожніє або коротшає до
неречення: краще лишити брудний фрагмент видимим для гейта, ніж поставити на його місце
уламок, що виглядає чистим. Не видаляє прольотів: `evidence_spans` не має стану, і
видалення зсунуло б порядок. Не чинить те, у чому речення немає взагалі — 22 прольоти,
де межа розрізала JSON банера згоди, лишаються як названий борг.

    repair_span_markup.py --database DB            # показати, нічого не писати
    repair_span_markup.py --database DB --apply
    repair_span_markup.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api/src"))

from korpus.infrastructure.extraction import _strip_html

#: Ті самі ознаки, що в `validate_span_hygiene.py`. Свідомо продубльовані ЗНАЧЕННЯМ, а не
#: імпортом: гейт і ремонт мусять погоджуватись про те, що таке бруд, і розбіжність між
#: ними має бути видно як розбіжність чисел, а не сховатись у спільній змінній.
ESCAPED_MARKUP = re.compile(r"&lt;/?[a-z]|&#34;|&quot;|&amp;nbsp;")
CHROME = re.compile(r"(?i)\bcmp-|reset password|\bcookies?\b|\bconsent banner\b")

#: Скільки тексту дозволено втратити при ремонті. Розмітка коротка; якщо зникло більше
#: половини, зник не тег, а речення — і такий проліт лишається неторканим.
MIN_SURVIVING_RATIO = 0.5
#: Коротше за це — вже не свідчення, хоч би яким чистим виглядало.
MIN_LENGTH = 40

SELECT = (
    "SELECT s.id, s.text FROM evidence_spans s "
    "JOIN document_versions v ON v.id = s.version_id "
    "WHERE v.review_state = 'approved' AND v.is_current"
)


def dirty(text: str) -> bool:
    return bool(ESCAPED_MARKUP.search(text) or CHROME.search(text))


def repair(text: str) -> tuple[str | None, str]:
    """Полагоджений текст і причина відмови — або None, якщо ремонт не потрібен."""
    cleaned = _strip_html(text).strip()
    if not cleaned or len(cleaned) < MIN_LENGTH:
        return None, "ремонт лишає неречення"
    if len(cleaned) < len(text) * MIN_SURVIVING_RATIO:
        return None, "ремонт зʼїдає більше половини тексту"
    if dirty(cleaned):
        return None, "розмітка лишається після ремонту"
    return cleaned, ""


def plan(connection: sqlite3.Connection) -> tuple[list[tuple[str, str, str]], dict[str, int]]:
    repaired: list[tuple[str, str, str]] = []
    refused: dict[str, int] = {}
    for span_id, text in connection.execute(SELECT):
        if not dirty(text):
            continue
        cleaned, reason = repair(text)
        if cleaned is None:
            refused[reason] = refused.get(reason, 0) + 1
            continue
        repaired.append((str(span_id), text, cleaned))
    return repaired, refused


def apply(connection: sqlite3.Connection, changes: list[tuple[str, str, str]]) -> None:
    connection.executemany(
        "UPDATE evidence_spans SET text = ?, text_hash = ? WHERE id = ?",
        [(new, hashlib.sha256(new.encode("utf-8")).hexdigest(), sid) for sid, _old, new in changes],
    )
    connection.commit()


def selftest() -> int:
    """Отрути по ДАНИХ: ремонт мусить відмовлятись там, де він шкідливий."""
    results: list[bool] = []

    def check(name: str, got: object, want: object) -> None:
        ok = got == want
        results.append(ok)
        print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: {got!r}")

    doctrine = "Командир бригади відповідає за бойову готовність підпорядкованих підрозділів."
    check("чистий текст ремонту не потребує", dirty(doctrine), False)

    dirty_but_real = "&lt;p>" + doctrine
    cleaned, _ = repair(dirty_but_real)
    check("справжнє речення чиститься", cleaned, doctrine)

    check("сама лише розмітка не ремонтується", repair("&lt;p>&lt;/p>&#34;")[0], None)
    check(
        "ремонт, що зʼїдає більшість, відхилено",
        repair("&lt;a href=x>" + "&lt;div>" * 40 + " коротко")[0],
        None,
    )
    only_chrome = "We use cookies to understand additional site usage on this page."
    check("хром без розмітки не «лагодиться» мовчки", repair(only_chrome)[0], None)

    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE evidence_spans (id TEXT, version_id TEXT, text TEXT, text_hash TEXT);"
        "CREATE TABLE document_versions (id TEXT, review_state TEXT, is_current INTEGER);"
    )
    connection.execute("INSERT INTO document_versions VALUES ('v1','approved',1)")
    connection.execute("INSERT INTO document_versions VALUES ('v2','draft',1)")
    connection.execute("INSERT INTO evidence_spans VALUES ('s1','v1',?,'x')", (dirty_but_real,))
    connection.execute("INSERT INTO evidence_spans VALUES ('s2','v2',?,'x')", (dirty_but_real,))
    connection.commit()
    changes, _ = plan(connection)
    check("нецитовна версія не чіпається", [c[0] for c in changes], ["s1"])
    apply(connection, changes)
    stored, stored_hash = connection.execute(
        "SELECT text, text_hash FROM evidence_spans WHERE id='s1'"
    ).fetchone()
    check("хеш описує те, що лежить", stored_hash, hashlib.sha256(stored.encode()).hexdigest())
    check("повторний прогін нічого не змінює", plan(connection)[0], [])

    passed = sum(1 for r in results if r)
    print(f"негативний контроль: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    if not arguments.database:
        parser.error("потрібен --database")

    connection = sqlite3.connect(arguments.database)
    before = sum(1 for _, text in connection.execute(SELECT) if dirty(text))
    changes, refused = plan(connection)
    if arguments.apply:
        apply(connection, changes)
    after = sum(1 for _, text in connection.execute(SELECT) if dirty(text))
    connection.close()
    print(
        json.dumps(
            {
                "schema": "korpus.span-markup-repair.v1",
                "dirty_before": before,
                "repairable": len(changes),
                "refused": refused,
                "dirty_after": after if arguments.apply else "не застосовано",
                "applied": arguments.apply,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
