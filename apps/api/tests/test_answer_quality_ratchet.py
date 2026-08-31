"""Дві протилежні межі якості відповідей, і жодна не рухається мовчки.

Ратчет на одній осі не відрізняє систему, що відповідає на все, від системи, що не
відповідає ні на що. Тому підлога на своїх питаннях і стеля на чужих тримаються разом.

Виміряно 31.08.2026 на живому розгортанні: 0.95 своїх і 0.20 чужих. До підняття порогу
покриття друга вісь була 0.85 — сімнадцять чужих питань із двадцяти під зеленим вироком.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from check_answer_quality_ratchet import problems  # noqa: E402

CONFIG: dict = {
    "measured": {"set_digest": "12cef2e250cba405"},
    "floors": {"in_corpus_answered_rate": 0.9},
    "ceilings": {"out_of_corpus_answered_rate": 0.25},
    "relaxed": [],
}
GOOD: dict = {
    "status": "MEASURED",
    "set_digest": "12cef2e250cba405ff",
    "in_corpus": {"rate": 0.95},
    "out_of_corpus": {"rate": 0.2},
}


def test_a_measurement_inside_both_bounds_passes() -> None:
    """Негативний контроль до решти: ратчет, що відхиляє все, не є ратчетом."""
    assert problems(GOOD, CONFIG) == []


def test_answering_fewer_of_our_own_questions_is_caught() -> None:
    assert problems({**GOOD, "in_corpus": {"rate": 0.85}}, CONFIG)


def test_letting_in_more_foreign_questions_is_caught() -> None:
    """Вісь, заради якої все почалось: 17 із 20 чужих питань під зеленим вироком."""
    assert problems({**GOOD, "out_of_corpus": {"rate": 0.3}}, CONFIG)


def test_a_run_that_never_reached_the_server_is_not_perfect_restraint() -> None:
    """`0.0` і «не міряли» в теці доказів виглядають однаково — і це різні речі."""
    assert problems({**GOOD, "status": "UNKNOWN"}, CONFIG)


def test_a_different_question_set_makes_the_numbers_incomparable() -> None:
    assert problems({**GOOD, "set_digest": "deadbeefdeadbeef"}, CONFIG)


def test_a_relaxed_bound_without_a_written_reason_is_refused() -> None:
    relaxed = {**CONFIG, "relaxed": [{"axis": "in_corpus_answered_rate", "reason": "-"}]}

    assert problems(GOOD, relaxed)


def test_a_relaxed_bound_with_a_reason_is_allowed() -> None:
    """Межу можна зсунути — але тільки назвавши, чому. Заборона рухати межі назавжди
    робить ратчет брехливим при першій же законній зміні корпусу."""
    relaxed = {
        **CONFIG,
        "relaxed": [
            {
                "axis": "in_corpus_answered_rate",
                "reason": "корпус звужено до публічної вибірки, частина питань більше не має джерела",
            }
        ],
    }

    assert problems(GOOD, relaxed) == []


def test_the_shipped_configuration_is_readable_and_two_sided() -> None:
    config = json.loads((ROOT / "config/operations/answer-quality-ratchet.json").read_text("utf-8"))

    assert config["floors"]["in_corpus_answered_rate"] > 0
    assert config["ceilings"]["out_of_corpus_answered_rate"] < 1
    assert config["why"], "межі без записаної причини — це числа, а не рішення"
