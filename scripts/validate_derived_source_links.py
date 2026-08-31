#!/usr/bin/env python3
"""Посилання перевіряється текстом джерела, на яке воно вказує, а не своєю формою.

`measure_corpus_integrity.py` рахує `citation_traceability` як частку версій, чий
`source_uri` не є голим доменом. Це вимір ФОРМИ, і він сам це декларує. Наслідок виміряний
адверсарним прогоном 31.08.2026: усі 97 похідних статей перевели на завідомо хибний статут
(вартові й днювальні — у дисциплінарний), і вісь лишилась байт у байт `0.95703125`, код
виходу 0. Сторож не боронив нічого з того, заради чого існує.

Тут перевірка інша: беремо `source_uri` похідної статті, знаходимо версію, яка цим URI
ПРЕДСТАВЛЕНА, читаємо її текст з object-store за `object_key` — і вимагаємо, щоб початок
похідного документа був підрядком цього тексту.

**Читається оригінал, не прольоти.** Зшивання прольотів встик вставляє перекриття,
обрізане посеред слова: виміряно 325 сфабрикованих стиків із 533 у 548-14, з текстом на
кшталт `«…зберігати державну таємницю.едоторканність…»`, якого в документі немає. На
рішення це не вплинуло (жодне з 1591 фейкових вікон не є справжнім текстом ніде в корпусі),
але перевірка не має права спиратись на текст, якого не існує. Object-store звіряється з
`document_versions.source_hash`, тож він і є джерелом.

**Проба спадає.** Похідні статті витягнуті так, що текст перетікає в наступну роль:
«Начальник варти з охорони штабів… (ст.219)» на 100-му символі вже говорить про помічника
начальника варти. Тому пробуються префікси від довшого до коротшого, і береться найдовший,
який дає збіг. Коротший префікс тут не послаблення: він мусить збігтися з ОРИГІНАЛОМ, а не
з формою URI.

Коди виходу: 0 — кожне похідне посилання підтверджене текстом · 1 — є непідтверджені
· 2 — судити нема чого.

    validate_derived_source_links.py --database DB [--object-root ТЕКА]
    validate_derived_source_links.py --selftest
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
_DERIVED = ("Обов'язки:", "Обов’язки:")
_WHITESPACE = re.compile(r"\s+")
#: Голий домен — це ще НЕ посилання на документ. Його рахує `citation_traceability`;
#: тут він не є хибним посиланням, і зливати ці два класи означало б, що гейт червоніє
#: за відкритий борг і мовчить за хибну прив'язку — рівно навпаки до потрібного.
_BARE_DOMAIN = re.compile(r"https?://[^/]+/?$")
#: Від довшого до коротшого. 60 — межа, нижче якої збіг перестає бути свідченням: у
#: статутах трапляються однакові формулювання обов'язків.
PROBE_LENGTHS = (120, 100, 80, 60)


def normalise(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def confirm(head: str, source_text: str) -> int | None:
    """Довжина найдовшого префікса, підтвердженого джерелом, або None."""
    body = normalise(source_text)
    probe = normalise(head)
    for length in PROBE_LENGTHS:
        candidate = probe[:length]
        if len(candidate) == length and candidate in body:
            return length
    return None


def selftest() -> int:
    source = (
        "а" * 40
        + " Вивідний зобов'язаний охороняти пост і не залишати його без наказу. "
        + "б" * 200
    )
    long_head = "Вивідний зобов'язаний охороняти пост і не залишати його без наказу. " + "в" * 200
    cases = [
        (
            "текст джерела підтверджує початок",
            confirm(
                "Вивідний зобов'язаний охороняти пост і не залишати його без наказу." + "а" * 60,
                source,
            ),
            60,
        ),
        (
            "чужий текст не підтверджується",
            confirm(
                "Командир накладає стягнення на порушника військової дисципліни згідно з вимогами."
                * 3,
                source,
            ),
            None,
        ),
        (
            "довгий початок, що втікає в інший текст, підтверджується коротшим",
            confirm(long_head, source),
            60,
        ),
        ("порожній початок не підтверджується", confirm("", source), None),
        (
            "пробіли не вирішують",
            confirm(
                "Вивідний   зобов'язаний\nохороняти пост і не залишати його без наказу." + "а" * 60,
                source,
            ),
            60,
        ),
    ]
    failures = [f"{name}: {got!r} != {want!r}" for name, got, want in cases if got != want]
    print(json.dumps({"selftest": len(cases), "failed": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def measure(database: Path, object_root: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    by_uri: dict[str, str] = {}
    derived: list[tuple[str, str, str]] = []
    for row in connection.execute(
        """select d.id, d.canonical_title, v.source_uri, v.object_key
           from documents d join document_versions v on v.document_id = d.id"""
    ):
        title, uri, key = str(row["canonical_title"]), row["source_uri"], str(row["object_key"])
        if title.startswith(_DERIVED):
            derived.append((str(row["id"]), title, str(uri or "")))
        elif uri:
            # Перший, що представляє цей URI: похідні документи ділять URI батька, тож
            # кандидатом на «джерело» може бути лише не-похідний.
            by_uri.setdefault(str(uri), key)
    confirmed = 0
    unconfirmed: list[dict[str, Any]] = []
    no_source: list[dict[str, Any]] = []
    not_linked: list[str] = []
    lengths: dict[int, int] = {}
    for doc_id, title, uri in derived:
        if not uri or _BARE_DOMAIN.fullmatch(uri.strip()):
            not_linked.append(title)
            continue
        source_key = by_uri.get(uri)
        if source_key is None:
            no_source.append({"title": title, "uri": uri})
            continue
        head_row = connection.execute(
            """select s.text from evidence_spans s
               join document_versions v on v.id = s.version_id
               where v.document_id = ? order by s.ordinal limit 1""",
            (doc_id,),
        ).fetchone()
        path = object_root / source_key
        if head_row is None or not path.is_file():
            unconfirmed.append({"title": title, "uri": uri, "why": "немає тексту або об'єкта"})
            continue
        length = confirm(str(head_row["text"]), path.read_text(encoding="utf-8", errors="replace"))
        if length is None:
            unconfirmed.append({"title": title, "uri": uri, "why": "початок не знайдено в джерелі"})
        else:
            confirmed += 1
            lengths[length] = lengths.get(length, 0) + 1
    total = len(derived) - len(not_linked)
    return {
        "not_linked_yet": sorted(not_linked),
        "not_linked_count": len(not_linked),
        "schema": "korpus.derived-source-links.v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "database": str(database),
        "inputs": report_inputs(database, Path(__file__).resolve()),
        "inputs_digest": inputs_digest(report_inputs(database, Path(__file__).resolve())),
        "derived_documents": len(derived),
        "derived_with_a_document_link": total,
        "confirmed_by_source_text": confirmed,
        "unconfirmed": unconfirmed[:20],
        "unconfirmed_count": len(unconfirmed),
        "no_source_in_corpus": no_source[:20],
        "no_source_count": len(no_source),
        "confirmed_at_probe_length": dict(sorted(lengths.items(), reverse=True)),
        "rate": (confirmed / total) if total else None,
        "status": "MEASURED" if total else "UNKNOWN",
        "cannot_judge": [
            "Підтверджується, що текст походить із НАЗВАНОГО джерела. Чи є саме воно "
            "найдоречнішим із кількох, що містять той самий текст, — ні.",
            "Похідний документ, чийого джерела в корпусі немає, тут не звинувачується й не "
            "виправдовується: він рахується окремо.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--object-root", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "var/derived-source-links.json")
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
    report = measure(args.database, object_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "MEASURED":
        return 2
    return 1 if report["unconfirmed_count"] else 0


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
