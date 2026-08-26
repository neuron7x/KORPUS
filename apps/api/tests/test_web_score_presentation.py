"""RAG-019: the ranking score is not a calibrated probability, and the UI must say so.

The disclaimer existed in ``app.js`` but nothing held it there: deleting the line
changed no test, so the finding was recorded CLOSED with prose as its evidence.
These tests hold both the sentence and the gate that guards it.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP_JS = ROOT / "apps/web/public/app.js"
WEB_VALIDATOR = ROOT / "apps/web/scripts/validate.mjs"
DISCLAIMER = "Якість ранжування не є ймовірністю правильності"


def test_the_ui_states_that_the_score_is_not_a_probability() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert DISCLAIMER in source, (
        "the answer view renders retrieval_score as a number; without this sentence "
        "a ranking utility reads as a confidence"
    )


def test_the_score_is_labelled_as_a_ranking_utility_not_a_confidence() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "Якість ранжування" in source
    for forbidden in ("Впевненість", "Ймовірність правильності", "Confidence"):
        assert forbidden not in source, (
            f"{forbidden!r} presents an uncalibrated ranking score as a probability"
        )


def test_the_web_validator_enforces_the_disclaimer() -> None:
    """Otherwise this file is the only thing holding it, and it does not run in web CI."""

    validator = WEB_VALIDATOR.read_text(encoding="utf-8")
    assert DISCLAIMER in validator, (
        "apps/web/scripts/validate.mjs no longer checks for the disclaimer, so the "
        "web pipeline would accept a build that dropped it"
    )
