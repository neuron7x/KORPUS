"""Частка суб'єкта — стеля на весь інтернет там, де суб'єкт один.

ВИМІРЯНО 02.09.2026 з НАЯВНОГО `var/load-probe.json`, не новим прогоном. У фазі сплеску
(паралелізм 24, 758 запитів) відхилено **406**, і всі — з причиною
`subject_share_exhausted`. Через глобальну ємність — **жодного**.

    "spike": {"requests": 758, "refusal_reasons": {"subject_share_exhausted": 406}}

Отже понад половину трафіку відхилено не тому, що сервіс повний, а тому, що вичерпано
частку ОДНОГО суб'єкта. На публічній межі це фатально: `api/answering.py:49` бере
`identity.subject`, і всі відвідувачі приходять під одним іменем. «Половина ємності»
перестає бути ізоляцією між орендарями й стає стелею на всіх разом.

Доказ лежав у дереві з 31.08 і чекав, поки його прочитають. Це той самий клас, що
«помічено ≠ виміряно», лише навпаки: ВИМІРЯНО і не прочитано.

Дефолт лишається половиною НАВМИСНО. Ізоляція правильна там, де суб'єктів багато, і
знімати її для всіх заради одного розгортання означало б поміняти одну ваду на іншу.
Розгортання з одним суб'єктом оголошує стелю ЯВНО — рішення, а не дефолт.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from korpus.application.resilience import AdmissionController
from korpus.config import Settings

ROOT = Path(__file__).resolve().parents[3]
PROBE = ROOT / "var/load-probe.json"


def test_the_default_still_isolates_tenants():
    """Без явного рішення жоден суб'єкт не забирає сервіс цілком."""
    controller = AdmissionController(8, 0.05)
    assert controller.per_subject_limit == 4
    assert AdmissionController(1, 0.05).per_subject_limit == 1, "ємність 1 мусить когось пускати"


def test_a_named_share_overrides_the_default():
    """Негативний контроль: без цього параметр був би оголошений і недосяжний."""
    controller = AdmissionController(8, 0.05, per_subject_limit=8)
    assert controller.per_subject_limit == 8
    assert controller.per_subject_limit != AdmissionController(8, 0.05).per_subject_limit


def test_the_setting_reaches_the_controller():
    """Параметр конфігу мусить ДОХОДИТИ, інакше він лише напис."""
    assert Settings().max_answers_per_subject is None, "дефолт не сміє мовчки змінитись"
    assert Settings(max_answers_per_subject=32).max_answers_per_subject == 32


def test_the_measured_refusals_were_the_subject_share_and_not_capacity():
    """Прив'язка твердження до ДОКАЗУ, а не до пам'яті про нього.

    Якщо звіт перевимірять і причина стане іншою, цей тест почервоніє й змусить
    переписати обґрунтування замість того, щоб воно тихо пережило свій вимір.
    """
    if not PROBE.is_file():
        pytest.skip("var/load-probe.json відсутній: без нього твердження не перевіряється")
    spike = json.loads(PROBE.read_text(encoding="utf-8")).get("spike", {})
    reasons = spike.get("refusal_reasons") or {}
    assert reasons.get("subject_share_exhausted", 0) > 0, (
        "звіт більше не показує вичерпання частки суб'єкта — обґрунтування застаріло"
    )
    assert not reasons.get("global_capacity"), (
        "з'явилися відмови через глобальну ємність: вузьке місце змістилось, "
        f"і причину треба переміряти: {reasons}"
    )
