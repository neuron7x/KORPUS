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

ПЕРЕВИМІРЯНО 04.09.2026 на пілоті, і твердження звузилось. Стара проба тримала ОДИН
токен, тобто одного суб'єкта, хай яким був `--concurrency`; відмови за часткою були
властивістю проби, а не розгортання, якому оголошено 3–10 РІЗНИХ користувачів. З
чотирма суб'єктами вузьке місце змістилось на ГЛОБАЛЬНУ ємність, і це вже властивість
розгортання: `KORPUS_MAX_CONCURRENT_ANSWERS=4`.

Тобто обидва твердження істинні про різні світи: на публічній межі, де суб'єкт один,
стеля частки — стеля на всіх; на пілоті, де суб'єктів багато, першою впирається
глобальна ємність. Тест в'яже кожне до звіту, а не до пам'яті про нього.
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


#: Причина, яка мусить переважати у сплеску на ПІЛОТІ — розгортанні з багатьма
#: суб'єктами. Ім'я те саме, що пише виробник (`application/overload.py`): звірятись із
#: ключем, якого продюсер не емітує, означає стерегти те, чого не буває. Саме так тут
#: і стояло: `reasons.get("global_capacity")` при виробнику `global_capacity_exhausted`,
#: тож умова була істинною завжди й не могла почервоніти.
DOMINANT_SPIKE_REFUSAL = "global_capacity_exhausted"
SUBJECT_SHARE_REFUSAL = "subject_share_exhausted"


def test_the_spike_refusals_name_a_cause_and_the_cause_is_the_declared_ceiling():
    """Прив'язка твердження до ДОКАЗУ, а не до пам'яті про нього.

    Якщо звіт перевимірять і причина стане іншою, цей тест почервоніє й змусить
    переписати обґрунтування замість того, щоб воно тихо пережило свій вимір.
    """
    if not PROBE.is_file():
        pytest.skip("var/load-probe.json відсутній: без нього твердження не перевіряється")
    report = json.loads(PROBE.read_text(encoding="utf-8"))
    spike = report.get("spike", {})
    reasons = spike.get("refusal_reasons") or {}
    assert reasons, (
        "сплеск не знайшов точки насичення: прогін без жодної відмови не доводить, "
        f"де стеля розгортання: {spike.get('statuses')}"
    )
    dominant = max(reasons, key=lambda name: reasons[name])
    subjects = int(report.get("subjects", 1))
    if subjects > 1:
        assert dominant == DOMINANT_SPIKE_REFUSAL, (
            "на розгортанні з кількома суб'єктами першою мусить впиратись ГЛОБАЛЬНА "
            f"ємність; переважає {dominant!r}: {reasons}"
        )
    else:
        assert dominant == SUBJECT_SHARE_REFUSAL, (
            f"де суб'єкт один, стеля частки — стеля на всіх; переважає {dominant!r}: {reasons}"
        )
