#!/usr/bin/env python3
"""Gate: a source our own extractor refuses is not "available".

The defect this exists for, found in the catalogue on 2026-08-29: `ORG-MECH-STATUTE-P3`
carried `ingestible: true` while the extractor rejected it — "PDF page count exceeds
configured limit" on a 20.4 MB file. The catalogue said take it; the code that would take
it said no. Nothing compared the two, so the contradiction sat in the record as a fact.

`machine_readable: false` would have been the wrong place to record it and a lie besides:
the text layer is there. What refuses is OUR side. That distinction is the whole content
of this gate — a limit we configured is a fact about us, and calling it a property of the
document hides the one thing that could be changed.

The classes are machine-readable, not prose, because a reason written as a sentence cannot
be counted, and an untyped refusal is indistinguishable from a note somebody left. Two
kinds are separated deliberately:

  * ours   — extractor_refused, too_few_words: we could lift these by changing our limits.
  * theirs — http_forbidden, rights_reserved, dns_unresolved, tls_refused, transport_*:
             nothing we change makes the artifact arrive.

A refusal of the first kind on an ingestible source is a contradiction and fails. A
refusal of the second kind on an ingestible source is a different contradiction — the
catalogue promises content that never arrived — and fails too. What does not fail is a
refusal recorded against a source already blocked: that is the record working as intended.

`--selftest` mutates each rule and requires it to fire.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from threshold_distance import place

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"

#: Відмова з НАШОГО боку: знімається зміною наших налаштувань.
OURS = {
    "extractor_refused",
    "too_few_words",
    #: Наш класифікатор помилився: вміст саме той, що обіцяно, а нюхач типу збито
    #: довгими рядками ВБУДОВАНОГО скрипту. Стан живе на нашому боці, бо лагодити
    #: треба нас, а не сторінку. Без нього дефект нюхача записувався у провину
    #: джерелу й переживав причину, яка його породила: два валідні HTML-документи
    #: (13 633 і 2 321 слово) стояли як «сервер віддав не те».
}
#: ОКРЕМА категорія, не підмножина OURS, і різниця тут вирішальна.
#: `extractor_refused` означає «ми не можемо це прочитати» — і `ingestible: true`
#: поруч із ним є суперечністю. `extractor_misclassified` означає «ми прочитали
#: НЕПРАВИЛЬНО, а вміст справний» — і тут суперечності немає: блокувати джерело
#: за нашою ж помилкою було б рівно тим, від чого цей гейт захищає.
#: Перша версія цього гейта саме так і робила: я поклала обидва стани в OURS і
#: почервоніла на двох валідних документах. Запис лишається видимим і старіє —
#: якщо класифікатор ніхто не полагодив, мовчазний «відомий баг» стає вироком.
MISCLASSIFIED = {"extractor_misclassified"}
#: Скільки днів «наш класифікатор помилився» лишається відомим багом, а не боргом.
MISCLASSIFICATION_GRACE_DAYS = 30
#: Відмова з боку джерела: наші налаштування на неї не впливають.
THEIRS = {
    "no_uri",
    "rights_reserved",
    "http_forbidden",
    "http_error",
    "transport_reset",
    "transport_timeout",
    "dns_unresolved",
    "tls_refused",
    #: Сервер віддає не той тип, що обіцяє URL (JS під HTML). Відмовляється НАШ
    #: екстрактор, але причина на боці джерела — і саме тому клас лежить тут, а не
    #: в OURS: зміна наших налаштувань не змусить сторінку віддати HTML.
    "content_type_mismatch",
}
CLASSES = OURS | THEIRS | MISCLASSIFIED
REFUSAL_MAX_AGE_DAYS = 365
#: Скільки днів відмова, позначена `retryable`, лишається «спробуй ще», а не вироком.
#: Мережева невдача сьогодні — це не факт про джерело, і записати за нею `ingestible:
#: false` означало б повторити найдорожчу помилку цього дерева: хибне «dead» тихо
#: викидає дозволений документ, і слід лишається в полі, якого ніхто не перечитує
#: (так було втрачено чотири відкриті Distribution A документи). Але й лежати вічно
#: вона не сміє: відмова місячної давнини, яку ніхто не перепробував, — це вже не
#: «спробуй ще», а невиміряне джерело, що видає себе за придатне.
RETRY_WINDOW_DAYS = 7


def _shape_problems(identifier: str, refusal: dict) -> tuple[list[str], int | None]:
    """Чи запис про відмову взагалі є записом — і скільки йому днів.

    Повертає (проблеми, вік). Вік `None` означає, що дата нечитана: далі йти нема з чим,
    бо кожне наступне правило — про те, СКІЛЬКИ вимір стоїть непереглянутим.
    """
    found: list[str] = []
    klass = str(refusal.get("class", ""))
    if klass not in CLASSES:
        return [
            f"{identifier}: unknown evidence_refusal.class {klass!r} — an untyped "
            "refusal cannot be counted and reads as a note somebody left"
        ], None
    if not str(refusal.get("reason", "")).strip():
        found.append(
            f"{identifier}: evidence_refusal has no reason — a class without the "
            "observation behind it cannot be reviewed or lifted"
        )
    try:
        age = (date.today() - date.fromisoformat(str(refusal.get("observed_on")))).days
    except ValueError:
        found.append(f"{identifier}: evidence_refusal.observed_on is not an ISO date")
        return found, None
    if age > REFUSAL_MAX_AGE_DAYS:
        found.append(
            f"{identifier}: refusal observed {age} days ago, over the "
            f"{REFUSAL_MAX_AGE_DAYS}-day floor — a limit we since changed still reads as current"
        )
    if age < 0:
        found.append(f"{identifier}: evidence_refusal.observed_on is in the future")
    return found, age


def _contradiction(identifier: str, refusal: dict, age: int) -> str | None:
    """Чи `ingestible: true` суперечить цій відмові — і чи вже суперечить.

    Три відповіді, бо станів справді три: свіжа мережева невдача — застарілий вимір;
    наша власна помилка класифікації — відомий баг, доки хтось його не полишив надовго;
    решта — суперечність одразу.
    """
    klass = str(refusal.get("class", ""))
    retryable = refusal.get("retryable")
    if not isinstance(retryable, bool):
        return (
            f"{identifier}: evidence_refusal.retryable is {retryable!r}, not a boolean — "
            'the string "False" is truthy, so every refusal would read as retryable'
        )
    if retryable and age <= RETRY_WINDOW_DAYS:
        return None
    if klass in MISCLASSIFIED:
        if age <= MISCLASSIFICATION_GRACE_DAYS:
            return None
        return (
            f"{identifier}: our classifier has been wrong about this source for {age} days "
            "and nobody fixed it — a known bug nobody acts on is a debt recorded as a fact"
        )
    side = "our own extractor" if klass in OURS else "the source"
    stale = f" and nobody retried it in {age} days" if retryable else ""
    return (
        f"{identifier}: ingestible=true while {side} refused it "
        f"({klass}: {str(refusal.get('reason', ''))[:90]}){stale} — the catalogue says "
        "take this and the code that would take it says no"
    )


def problems(entries: list[dict]) -> list[str]:
    found: list[str] = []
    for entry in entries:
        identifier = str(entry.get("id", "<no id>"))
        refusal = entry.get("evidence_refusal")
        if refusal is None:
            continue
        if not isinstance(refusal, dict):
            found.append(f"{identifier}: evidence_refusal is not an object")
            continue
        shape, age = _shape_problems(identifier, refusal)
        found.extend(shape)
        if age is None or not entry.get("ingestible"):
            continue
        clash = _contradiction(identifier, refusal, age)
        if clash:
            found.append(clash)
    return found


PROBE_BASE: dict[str, Any] = {
    "id": "T",
    "ingestible": False,
    "evidence_refusal": {
        "class": "extractor_refused",
        "reason": "extractor refused: PDF page count exceeds configured limit",
        "retryable": False,
        "observed_on": "",
    },
}

PROBES: tuple[tuple[str, object, bool], ...] = (
    ("заблоковане джерело з відмовою — запис працює як задумано", {}, False),
    ("джерело без evidence_refusal ігнорується", [{"id": "T", "ingestible": True}], False),
    ("відмова НАШОГО екстрактора при ingestible", {"ingestible": True}, True),
    (
        "відмова ДЖЕРЕЛА при ingestible",
        {"ingestible": True, "class": "http_forbidden", "reason": "HTTP 403"},
        True,
    ),
    ("невідомий клас відмови", {"class": "щось пішло не так"}, True),
    ("клас є, причини немає", {"reason": "   "}, True),
    ("відмова не об'єкт", {"evidence_refusal": "не вдалося"}, True),
    ("дата не ISO", {"_observed_days_ago": None}, True),
    ("відмова протухла", {"_observed_days_ago": REFUSAL_MAX_AGE_DAYS + 1}, True),
    ("відмова рівно на межі віку", {"_observed_days_ago": REFUSAL_MAX_AGE_DAYS}, False),
    ("дата в майбутньому", {"_observed_days_ago": -1}, True),
    ("клас із боку джерела на заблокованому — норма", {"class": "dns_unresolved"}, False),
    # content_type_mismatch: відмовився наш екстрактор, причина на боці джерела.
    (
        "невідповідність типу вмісту при ingestible",
        {
            "ingestible": True,
            "class": "content_type_mismatch",
            "reason": "HTML content detected as application/javascript",
            "retryable": False,
        },
        True,
    ),
    # Наш класифікатор помилився, вміст справний → джерело НЕ блокується.
    (
        "помилка класифікатора при ingestible НЕ червоніє",
        {
            "ingestible": True,
            "class": "extractor_misclassified",
            "reason": "sniffer read inline script as a JavaScript document",
            "retryable": False,
        },
        False,
    ),
    (
        "помилка класифікатора, якої ніхто не полагодив за місяць — червоніє",
        {
            "ingestible": True,
            "class": "extractor_misclassified",
            "reason": "нюхач помилився",
            "retryable": False,
            "_observed_days_ago": MISCLASSIFICATION_GRACE_DAYS + 1,
        },
        True,
    ),
    (
        "рівно на межі пільги — ще не борг",
        {
            "ingestible": True,
            "class": "extractor_misclassified",
            "reason": "нюхач помилився",
            "retryable": False,
            "_observed_days_ago": MISCLASSIFICATION_GRACE_DAYS,
        },
        False,
    ),
    (
        "помилка класифікатора на заблокованому — норма",
        {"class": "extractor_misclassified", "reason": "нюхач помилився"},
        False,
    ),
    # А «ми НЕ МОЖЕМО прочитати» лишається суперечністю з ingestible.
    (
        "наш ліміт при ingestible усе одно червоніє",
        {
            "ingestible": True,
            "class": "extractor_refused",
            "reason": "PDF page count exceeds configured limit",
            "retryable": False,
        },
        True,
    ),
    (
        "невідповідність типу вмісту на заблокованому — норма",
        {"class": "content_type_mismatch", "reason": "JS під HTML-URL"},
        False,
    ),
    # retryable: свіжа мережева невдача — застарілий вимір, а не вирок про джерело.
    (
        "свіжа мережева невдача при ingestible НЕ червоніє",
        {
            "ingestible": True,
            "class": "transport_reset",
            "reason": "connection reset",
            "retryable": True,
        },
        False,
    ),
    (
        "та сама невдача, якої ніхто не перепробував за тиждень — червоніє",
        {
            "ingestible": True,
            "class": "transport_reset",
            "reason": "connection reset",
            "retryable": True,
            "_observed_days_ago": RETRY_WINDOW_DAYS + 1,
        },
        True,
    ),
    (
        "рівно на межі вікна повтору — ще не вирок",
        {
            "ingestible": True,
            "class": "transport_reset",
            "reason": "connection reset",
            "retryable": True,
            "_observed_days_ago": RETRY_WINDOW_DAYS,
        },
        False,
    ),
    (
        "НЕ-retryable при ingestible червоніє одразу",
        {"ingestible": True, "class": "http_error", "reason": "HTTP 404", "retryable": False},
        True,
    ),
    # `bool("False")` дорівнює True — рядок замість bool вимикав би все правило.
    ("retryable рядком, а не булевим", {"ingestible": True, "retryable": "False"}, True),
    ("retryable відсутній", {"ingestible": True, "retryable": None}, True),
    ("too_few_words на заблокованому — норма", {"class": "too_few_words"}, False),
)


def _probe_entries(changes: object) -> list[dict[str, Any]]:
    if isinstance(changes, list):
        return changes
    if not isinstance(changes, dict):
        raise TypeError(f"проба {changes!r} — ні список записів, ні набір змін")
    entry: dict[str, Any] = copy.deepcopy(PROBE_BASE)
    refusal = entry["evidence_refusal"]
    refusal["observed_on"] = date.today().isoformat()
    for key, value in changes.items():
        if key == "_observed_days_ago":
            refusal["observed_on"] = (
                "вчора"
                if value is None
                else date.fromordinal(date.today().toordinal() - int(value)).isoformat()
            )
        elif key in entry:
            entry[key] = value
        else:
            refusal[key] = value
    return [entry]


def selftest() -> int:
    bad = 0
    for name, changes, want_fail in PROBES:
        got = bool(problems(_probe_entries(changes)))
        if got != want_fail:
            bad += 1
            print(f"  ✗ {name}: очікували {'падіння' if want_fail else 'PASS'}")
        else:
            print(f"  ✓ {name}")
    split_ok = (
        OURS.isdisjoint(THEIRS)
        and OURS.isdisjoint(MISCLASSIFIED)
        and THEIRS.isdisjoint(MISCLASSIFIED)
        and CLASSES >= OURS | MISCLASSIFIED
    )
    bad += not split_ok
    print(
        f"  {'✓' if split_ok else '✗'} три категорії не перетинаються "
        f"(наш ліміт {len(OURS)} · бік джерела {len(THEIRS)} · "
        f"наша помилка {len(MISCLASSIFIED)})"
    )
    total = len(PROBES) + 1
    print(f"негативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    entries = data["sources"] if isinstance(data, dict) else data
    found = problems(entries)
    recorded = [e for e in entries if isinstance(e.get("evidence_refusal"), dict)]

    def by(group: set[str]) -> list[dict]:
        return [e for e in recorded if e["evidence_refusal"].get("class") in group]

    ours, theirs, wrong = by(OURS), by(THEIRS), by(MISCLASSIFIED)
    if found:
        print("evidence refusals: FAIL")
        for item in found:
            print(f"  ✗ {item}")
        return 1
    #: Часові пороги цього гейта не мають ЖОДНОГО спостереження в перший день: усе
    #: виміряно щойно. Мовчати про це означало б дати зеленому числу вигляд перевіреного.
    ages = []
    for e in recorded:
        try:
            ages.append(
                float(
                    (
                        date.today()
                        - date.fromisoformat(str(e["evidence_refusal"].get("observed_on")))
                    ).days
                )
            )
        except ValueError:
            continue
    print("evidence refusals: PASS")
    for label, value in (
        ("RETRY_WINDOW_DAYS", RETRY_WINDOW_DAYS),
        ("MISCLASSIFICATION_GRACE_DAYS", MISCLASSIFICATION_GRACE_DAYS),
    ):
        print(f"  {label} = {value}: {place(value, ages, 'днів').note}")
    print(
        f"  {len(recorded)} refusals recorded · {len(ours)} a limit of ours to lift · "
        f"{len(theirs)} the source's, nothing we change reaches them · "
        f"{len(wrong)} our own classifier was wrong and the content is fine"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
