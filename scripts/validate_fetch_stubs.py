#!/usr/bin/env python3
"""Сторінка, яку видавець сам оголосив невідображеною, не є документом.

П'ять документів бойового корпусу мають авторитетну українську назву й НЕ мають
жодного рядка нормативного тексту: `Стройовий статут Збройних Сил України`, закон
про пенсійне забезпечення військових, накази Міноборони № 402, № 317 і № 444 — ті
самі переліки ВОС, заради яких їх і брали. У сховищі замість документа лежить
обгортка zakon.rada: «Нормальне відображення сторінки не можливе через відсутність
багатьох потрібних функцій», назва, повторена п'ять разів, і посилання. Прольоти
з них `approved` і `is_current`, тобто солдату просто зараз можна процитувати
Стройовий статут — і цитатою буде його власна назва.

ЧОМУ ГЕЙТ НЕ МІРЯЄ ТЕКСТ. Спробувано три осі, жодна не розділяє:
  · довжина нового тексту поза назвою — порожні сторінки мають 842–1202 символи,
    а ЗАКОННІ картки обов'язків («Днювальний парку», ст.358) — 231–595. Порожнє
    довше за справжнє;
  · регулярка на нормативні ознаки («стаття N», «пункт N») — при зміні одного
    альтернативного шаблону вирок перекинувся на трьох документах, тобто міряла
    себе, а не корпус;
  · наявність речення — 105 із 256 документів не мають жодного рядка ≥80 символів
    із крапкою, серед них методичні рекомендації на 131 проліт.
Тому ознака СТРУКТУРНА, а не статистична: видавець власним текстом заявив, що
віддав не документ. Це факт про відповідь сервера, а не оцінка змісту.

ЩО ГЕЙТ НЕ ВИРІШУЄ. Чи лишився в об'єкті придатний зміст попри обгортку — рішення
людини. Три з дев'яти сторінок zakon.rada несуть 14–28 тисяч символів наказу
поруч із обгорткою, і викидати їх автоматично було б гірше, ніж лишити.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

#: Кожен запис — ВЛАСНА заява видавця, дослівно, а не наш здогад про якість.
PUBLISHER_FAILURE = {
    "zakon.rada.gov.ua": re.compile(r"Нормальне відображення сторінки не можливе"),
    "javascript-required": re.compile(r"(?i)enable javascript|увімкніть javascript"),
    "bot-challenge": re.compile(r"(?i)just a moment|checking your browser|attention required"),
}


def failure_signature(text: str) -> str | None:
    for name, pattern in PUBLISHER_FAILURE.items():
        if pattern.search(text):
            return name
    return None


def _normalise(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яїієґё]+", " ", value.lower()).strip()


def content_beyond_title(text: str, title: str) -> int:
    """Скільки символів у неповторних рядках, що не є відлунням назви.

    Довідково, НЕ вирок: див. докстрінг — саме ця величина не розділяє класи.
    """
    marker = _normalise(title)[:40]
    seen: set[str] = set()
    total = 0
    for line in text.splitlines():
        normalised = _normalise(line)
        if not normalised or normalised in seen:
            continue
        seen.add(normalised)
        if marker and (marker in normalised or normalised[:40] in _normalise(title)):
            continue
        total += len(normalised)
    return total


def scan(database: Path, objects: Path) -> dict[str, object]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT d.canonical_title, v.source_uri, v.object_key,"
            " (SELECT count(*) FROM evidence_spans s WHERE s.version_id = v.id)"
            " FROM document_versions v JOIN documents d ON d.id = v.document_id"
            " WHERE v.review_state = 'approved' AND v.is_current"
        ).fetchall()
    finally:
        connection.close()

    findings: list[dict[str, str | int]] = []
    checked = 0
    for title, uri, key, spans in rows:
        path = objects / str(key)
        if not path.is_file():
            continue
        checked += 1
        text = path.read_bytes().decode("utf-8", "replace")
        signature = failure_signature(text)
        if signature:
            findings.append(
                {
                    "title": str(title),
                    "source_uri": str(uri),
                    "citable_spans": int(spans),
                    "publisher_said": signature,
                    "content_beyond_title_chars": content_beyond_title(text, str(title)),
                }
            )
    findings.sort(key=lambda item: int(item["content_beyond_title_chars"]))
    return {
        "schema": "korpus.fetch-stub.v1",
        "documents_checked": checked,
        "documents_flagged": len(findings),
        "citable_spans_at_risk": sum(int(item["citable_spans"]) for item in findings),
        "findings": findings,
        "decision_for_a_person": (
            "Прапорець означає: видавець сам заявив, що сторінка не відобразилась. "
            "Чи лишився придатний зміст — рішення людини, і content_beyond_title_chars "
            "тут ДОВІДКА, а не поріг: законні короткі документи мають його менше, ніж "
            "порожні сторінки."
        ),
        "status": "PASS" if not findings else "FAIL",
    }


def selftest() -> int:
    """Негативні контролі: справжні короткі документи не сміють спрацьовувати."""
    cases = [
        (
            "заглушка zakon.rada",
            "Нормальне відображення сторінки не можливе\nчерез",
            "zakon.rada.gov.ua",
        ),
        ("вимога JavaScript", "Please enable JavaScript to view this page", "javascript-required"),
        ("бот-перевірка", "Just a moment... checking", "bot-challenge"),
        ("картка обов'язків", "Днювальний парку відповідає за схоронність машин.", None),
        ("стаття статуту", "Стаття 358. Днювальний парку призначається з рядових.", None),
        ("англійська доктрина", "The commander is responsible for protection.", None),
        ("слово javascript у тексті", "Сайт побудовано на JavaScript і HTML.", None),
    ]
    ok = 0
    for name, text, want in cases:
        got = failure_signature(text)
        good = got == want
        ok += good
        print(f"  {'ok' if good else 'ПРОВАЛ'} {name}: {got!r} (мало бути {want!r})")
    print(f"негативний контроль: {ok}/{len(cases)}")
    return 0 if ok == len(cases) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    parser.add_argument("--objects", type=Path)
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    if not arguments.database or not arguments.objects:
        parser.error("потрібні --database і --objects")
    report = scan(arguments.database, arguments.objects)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
