#!/usr/bin/env python3
"""Похідна стаття успадкувала титульну сторінку порталу замість джерела, з якого взята.

«Показати, ДЕ САМЕ це написано» — половина ціннісної функції. Виміряно 31.08.2026 на
базі, яка обслуговується: 108 із 256 версій мають `source_uri` виду
`https://zakon.rada.gov.ua/` — головну сторінку. Читач бачить кнопку «Відкрити точний
фрагмент», офіційну назву, хеш — і посилання на портал.

**Це не втрачені посилання.** 101 із 108 — похідні статті «Обов'язки: <роль>
(Статут, ст.N)», витягнуті з чотирьох статутів, кожен з яких лежить у цьому ж корпусі з
глибоким посиланням. Власного URL стаття не має й мати не може; успадкувати вона мусить
батьківський.

**Батько визначається ДОСЛІВНИМ ВХОДЖЕННЯМ, не назвою.** У назві сказано лише «Статут», а
їх чотири: внутрішньої служби (548-14), стройовий (549-14), гарнізонної та вартової служб
(550-14), дисциплінарний (551-14). Тому початок статті шукається як підрядок у тексті
кожного кандидата: збіг рівно з одним — прив'язка; збіг із кількома або з жодним — стаття
лишається як була і рахується окремо. Вибір за схожістю назви був би здогадом, а здогад
тут коштує хибного посилання під хешем.

**Читається ОРИГІНАЛ з object-store, не зшиті прольоти.** Перша версія цього інструмента
зшивала прольоти встик, спираючись на моє твердження, що стики суцільного зшивання є
справжніми стиками документа. Твердження СПРОСТОВАНЕ виміром 31.08.2026: у 548-14 із 533
стиків 325 містять текст, якого в документі немає, — перекриття прольотів вставляється
обрізаним посеред слова («…зберігати державну таємницю.едоторканність…»). На тодішні
рішення це не вплинуло (жодне з 1591 фейкових вікон не є справжнім текстом ніде в корпусі),
але спиратись на текст, якого не існує, не можна незалежно від того, чи пощастило. Об'єкт
звіряється з `document_versions.source_hash`, тож він і є документом.

**Проба спадає від 120 до 60.** Похідні статті витягнуті так, що текст перетікає в
наступну роль: «Начальник варти з охорони штабів… (ст.219)» на 100-му символі вже говорить
про помічника начальника варти, тож фіксовані 120 його втрачали. Береться найдовший
префікс, який дає рівно одного кандидата; нижче 60 збіг перестає бути свідченням, бо
формулювання обов'язків у статутах повторюються.

**Чого НЕ робить.** Не вигадує URL: копіює той, що вже стоїть у батька й перевірений.
Не ставить якір на статтю — `#n<номер>` на zakon.rada не виводиться з тексту, тож
посилання веде на документ, а не на абзац. Це названо, бо інакше читач вважатиме, що
«точний фрагмент» відкриється сам.

    relink_derived_articles.py --database DB          # показати
    relink_derived_articles.py --database DB --apply
    relink_derived_articles.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "var/runtime/corpus-v6-20260807/korpus.db"
_BARE_DOMAIN = re.compile(r"https?://[^/]+/?$")
_DERIVED = ("Обов'язки:", "Обов’язки:")
#: Від довшого до коротшого: довший префікс — сильніше свідчення, тож береться перший,
#: що дає однозначну відповідь.
PROBE_LENGTHS = (120, 100, 80, 60)
#: Нижче цього номер у назві не є свідченням: виміряно на 97 прив'язках, що «ст.N» —
#: номер СТАТТІ у 86 випадках і номер ЧАСТИНИ всередині статті в 11, і всі одинадцять
#: мають N ≤ 3 або форму «11-1». Тож на малих N цей розв'язувач мовчить.
SMALLEST_TRUSTED_ARTICLE = 10
_ARTICLE_IN_TITLE = re.compile(r"ст\.\s*(\d+)")
_ARTICLE_MARKER = re.compile(r"(?:^|\s)(\d{1,3})\.\s")
#: Скільки символів перед входженням дивитись у пошуках заголовка статті.
ARTICLE_LOOKBACK = 4000


def normalise(text: str) -> str:
    return " ".join(text.split())


def disambiguate(title: str, hits: list[str], bodies: dict[str, str], needle: str) -> str | None:
    """Другий, НЕЗАЛЕЖНИЙ сигнал, коли текст трапляється в кількох статутах.

    Текст «Начальник служби пожежної безпеки… (ст.195)» дослівно є і в 548-14, і в 550-14.
    Входженням це не розв'язується — воно вже сказало все, що могло. Але в 548-14 текст
    стоїть під статтею 195, а в 550-14 під статтею 21; номер у назві збігається рівно з
    одним. Це вимір іншої властивості, а не глибше вдивляння в ту саму.

    Мовчить, коли збігається нуль або більше одного кандидата: розв'язувач, який
    вгадує при нічиї, гірший за той, що відмовляється.
    """
    named = _ARTICLE_IN_TITLE.search(title)
    if not named or int(named.group(1)) < SMALLEST_TRUSTED_ARTICLE:
        return None
    wanted = int(named.group(1))
    agreeing = []
    for candidate in hits:
        at = bodies[candidate].find(needle)
        if at < 0:
            continue
        markers = _ARTICLE_MARKER.findall(bodies[candidate][:at][-ARTICLE_LOOKBACK:])
        if markers and int(markers[-1]) == wanted:
            agreeing.append(candidate)
    return agreeing[0] if len(agreeing) == 1 else None


def resolve(
    derived: list[tuple[str, str, str]], parents: dict[str, tuple[str, str]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Прив'язки, які доводяться входженням, і причини для решти."""
    bodies = {doc_id: normalise(text) for doc_id, (_url, text) in parents.items()}
    urls = {doc_id: url for doc_id, (url, _text) in parents.items()}
    links: list[dict[str, Any]] = []
    skipped = {"no_probe": 0, "not_found": 0, "ambiguous": 0}
    for doc_id, title, head in derived:
        probe = normalise(head)
        if not probe:
            skipped["no_probe"] += 1
            continue
        found: list[str] | None = None
        used = 0
        for length in PROBE_LENGTHS:
            needle = probe[:length]
            if len(needle) < length:
                continue
            hits = [parent for parent, body in bodies.items() if needle in body]
            if len(hits) == 1:
                found, used = hits, length
                break
            if len(hits) > 1:
                # Довший префікс уже не розрізнив — коротший розрізнить тим паче не зможе.
                # Лишається сигнал ІНШОЇ природи: номер статті в назві проти нумерації
                # кандидата.
                settled = disambiguate(title, hits, bodies, needle)
                found, used = ([settled], length) if settled else (hits, length)
                break
        if found is None or not found:
            skipped["not_found"] += 1
            continue
        if len(found) > 1:
            skipped["ambiguous"] += 1
            continue
        links.append(
            {
                "document_id": doc_id,
                "title": title,
                "parent": found[0],
                "url": urls[found[0]],
                "probe_chars": used,
            }
        )
    return links, skipped


def selftest() -> int:
    """Отрути по ДАНИХ: підмінюємо те, що інструмент читає, і дивимось, чи він відмовляє."""
    guard = "Вивідний зобов'язаний охороняти пост, не залишати його без наказу начальника варти та доповідати про кожне порушення негайно."
    discipline = "Командир накладає стягнення на порушника з урахуванням ступеня вини, попередньої поведінки та розміру завданих державі збитків."
    parents = {
        "p1": (
            "https://zakon.rada.gov.ua/laws/show/550-14/print",
            "Стаття 244. " + guard + " Далі йде інший текст.",
        ),
        "p2": ("https://zakon.rada.gov.ua/laws/show/551-14/print", "Стаття 104. " + discipline),
    }
    # Голова, що збігається перші 100 символів, а далі втікає в наступну роль — механізм,
    # через який фіксовані 120 губили «Начальник варти з охорони штабів… (ст.219)».
    runs_on = (
        guard[:100]
        + " Помічник начальника варти підпорядковується начальникові варти та виконує інші обов'язки."
    )
    cases: list[
        tuple[str, list[tuple[str, str, str]], dict[str, tuple[str, str]], int, str | None, int]
    ] = [
        (
            "однозначний збіг прив'язується",
            [("d", "Обов'язки: Вивідний", guard)],
            parents,
            1,
            None,
            120,
        ),
        (
            "текст, що втікає після 100, прив'язується КОРОТШИМ префіксом",
            [("d", "Обов'язки: Начальник варти", runs_on)],
            parents,
            1,
            None,
            100,
        ),
        (
            "нема збігу — лишаємо як було",
            [
                (
                    "d",
                    "Обов'язки: Хтось",
                    "Текст, якого немає в жодному статуті, і він достатньо довгий, щоб проба була змістовною зовсім.",
                )
            ],
            parents,
            0,
            "not_found",
            0,
        ),
        (
            "закороткий початок не прив'язується",
            [("d", "Обов'язки: Хтось", guard[:40])],
            parents,
            0,
            "not_found",
            0,
        ),
        (
            "порожня проба не прив'язується",
            [("d", "Обов'язки: Хтось", "   ")],
            parents,
            0,
            "no_probe",
            0,
        ),
        (
            "збіг у двох батьках — здогад заборонено",
            [("d", "Обов'язки: Хтось", guard)],
            {"p1": (parents["p1"][0], guard), "p2": (parents["p2"][0], guard)},
            0,
            "ambiguous",
            0,
        ),
    ]
    failures: list[str] = []
    for name, derived, catalogue, want_links, want_skip, want_chars in cases:
        links, skipped = resolve(derived, catalogue)
        if len(links) != want_links:
            failures.append(f"{name}: прив'язок {len(links)}, очікувалось {want_links}")
        elif want_skip and skipped[want_skip] != 1:
            failures.append(f"{name}: {want_skip}={skipped[want_skip]}")
        elif want_links and links[0]["probe_chars"] != want_chars:
            failures.append(f"{name}: префікс {links[0]['probe_chars']}, очікувався {want_chars}")
    print(json.dumps({"selftest": len(cases), "failed": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def load(
    connection: sqlite3.Connection, object_root: Path
) -> tuple[list[tuple[str, str, str]], dict[str, tuple[str, str]]]:
    """Похідні статті з голим доменом, і кандидати в батьки — з ОРИГІНАЛІВ."""
    parents: dict[str, tuple[str, str]] = {}
    derived: list[tuple[str, str, str]] = []
    for doc_id, title, uri, object_key in connection.execute(
        """select d.id, d.canonical_title, v.source_uri, v.object_key
           from documents d join document_versions v on v.document_id = d.id"""
    ):
        is_derived = str(title).startswith(_DERIVED)
        bare = uri and _BARE_DOMAIN.fullmatch(str(uri).strip())
        if is_derived and bare:
            head = connection.execute(
                """select s.text from evidence_spans s
                   join document_versions v on v.id = s.version_id
                   where v.document_id = ? order by s.ordinal limit 1""",
                (doc_id,),
            ).fetchone()
            derived.append((str(doc_id), str(title), str(head[0]) if head else ""))
        elif uri and not bare and not is_derived:
            path = object_root / str(object_key)
            if path.is_file():
                parents[str(doc_id)] = (
                    str(uri),
                    path.read_text(encoding="utf-8", errors="replace"),
                )
    return derived, parents


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--object-root", type=Path)
    parser.add_argument("--apply", action="store_true")
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
        print(
            json.dumps({"status": "UNKNOWN", "reason": f"немає {object_root}"}, ensure_ascii=False)
        )
        return 2
    connection = sqlite3.connect(str(args.database))
    derived, parents = load(connection, object_root)
    links, skipped = resolve(derived, parents)
    if args.apply:
        for link in links:
            connection.execute(
                "update document_versions set source_uri=? where document_id=?",
                (link["url"], link["document_id"]),
            )
        connection.commit()
    print(
        json.dumps(
            {
                "status": "PASS",
                "applied": bool(args.apply),
                "derived_articles": len(derived),
                "relinked": len(links),
                "probe_chars_used": {
                    str(length): sum(1 for link in links if link["probe_chars"] == length)
                    for length in PROBE_LENGTHS
                    if any(link["probe_chars"] == length for link in links)
                },
                "skipped": skipped,
                "anchor": "посилання веде на ДОКУМЕНТ, не на абзац: якір статті не виводиться з тексту",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


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
