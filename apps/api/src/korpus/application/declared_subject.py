"""Предмет, який документ оголошує про себе сам.

Корпус не лише зберігає текст — він каже, ПРО КОГО кожен документ: дев'яносто чотири
заголовки мають вигляд `Обов'язки: <роль> (Статут, ст.N)`. Це закритий словник, тож
збіг питання з ним точний — без міри схожості й без порога.

ЧОМУ. Виміряно 31.08.2026: на 101 питання «Які обов'язки має X?» перша цитата жодного
разу не була документом, що описує саме X. Нуль зі ста одного. Причина не в одній
стадії — чотири поспіль міряють, чи відповідь ПОВТОРЮЄ слова питання: добір кандидатів,
ранжування, покриття запиту, добір речень. Стаття з обов'язками ролі її назви не
повторює: назва в заголовку, а текст каже «Він зобов'язаний…». Для 67 зі 101 ролі її
документ не містить слів власної ролі взагалі.

Тому правило «повтори питання» відкидає саме ту статтю, яка Й Є відповіддю, і водночас
винагороджує довгий статут, що згадав роль мимохідь. Звідси й перевернута впевненість:
хибні відповіді звітували coverage 1.0, правильна — 0.8.

Тут не міра доречності, а допуск: слова предмета, який документ оголошує, покриті цим
документом — він про них і є. Немає збігу — нічого не змінюється.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

#: `Обов'язки: <роль> (…)`. Апостроф у назвах трапляється двома символами.
DECLARED_SUBJECT = re.compile(r"^Обов[’']язки:\s*(?P<subject>.+?)\s*\(")

#: Коротший предмет не розпізнається: «Солдат» збігся б із будь-яким текстом про
#: солдата й перетворив би допуск на шум.
MIN_SUBJECT_CHARS = 8


def declared_subject(title: str) -> str | None:
    matched = DECLARED_SUBJECT.match(title)
    if matched is None:
        return None
    subject = matched.group("subject").strip()
    return subject if len(subject) >= MIN_SUBJECT_CHARS else None


def subjects_in_question(question: str, titles: Iterable[str]) -> list[str]:
    """Заголовки, чий оголошений предмет названо в питанні дослівно.

    Довші предмети першими: «Заступник командира бригади» мусить виграти в «командира
    бригади», інакше питання про заступника віддасть документ командира — і навпаки.
    """
    lowered = question.lower()
    matched: list[tuple[str, str]] = []
    for title in titles:
        subject = declared_subject(title)
        if subject is not None and subject.lower() in lowered:
            matched.append((subject, title))
    matched.sort(key=lambda pair: len(pair[0]), reverse=True)
    return [title for _subject, title in matched]


def subject_tokens(titles: Iterable[str]) -> set[str]:
    """Слова оголошених предметів — ті, що документ покриває власною назвою."""
    tokens: set[str] = set()
    for title in titles:
        subject = declared_subject(title)
        if subject:
            tokens.update(re.findall(r"\w+", subject.lower()))
    return tokens


def declared_subject_documents(question: str, evidence: Iterable[object]) -> Mapping[str, int]:
    """Документи, чий оголошений предмет названо в питанні, і НАСКІЛЬКИ точно.

    Замикання словника тут суттєве: предмети беруться з ЗАГОЛОВКІВ самих кандидатів,
    а не з питання. Тому обійти допуск формулюванням не можна — щоб потрапити сюди,
    документ мусить уже існувати в корпусі й оголосити свій предмет сам.

    **Значення — довжина збігу, і це не оформлення.** Раніше поверталася множина, тож
    клас предмета був БІНАРНИЙ: питання «Які обов'язки має Безпосередні командири?»
    збігається з трьома оголошеними предметами — «Безпосередні командири» (22 символи)
    і двома «Командир» (по 8), бо коротший є підрядком довшого. Усі троє потрапляли в
    один клас і далі змагалися релевантністю, де узагальнення виграє: виміряно
    31.08.2026, ранжувальник ставив «Командир (начальник)» першим (0.4129) перед
    «Безпосередні командири» (0.3356).

    Порядок за довжиною вже обчислювався в `subjects_in_question` — і губився при
    перетворенні на множину. Тепер він доживає до ранжування. Перевірка `x in ...`
    працює як і раніше: у відображенні членство — це ключі.
    """
    titles: dict[str, list[str]] = {}
    for item in evidence:
        document = getattr(item, "document", None)
        title = getattr(document, "canonical_title", None)
        if title:
            titles.setdefault(title, []).append(str(getattr(document, "id", "")))
    specificity: dict[str, int] = {}
    for title in subjects_in_question(question, titles.keys()):
        subject = declared_subject(title) or ""
        for document_id in titles.get(title, []):
            if document_id:
                # Документ може мати кілька заголовків у видачі; лишається найточніший.
                specificity[document_id] = max(specificity.get(document_id, 0), len(subject))
    return specificity
