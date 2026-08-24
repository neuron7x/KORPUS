"""Rules carry their own examples, and the unknown case costs more than the ordinary one.

RAG-009 recorded two things in one sentence. "Перефразування обходить stricter
thresholds" is the coverage half: "Чи можу я виїхати без наказу?" contains none of the
vocabulary the old patterns looked for and was answered under the loosest evidence
requirement the system has — for a question about whether the reader may act.

The other half is the direction of failure, and it is the one that could not be fixed
by adding patterns. An unrecognised query fell to STANDARD, which is fail-open in the
one place this design is otherwise fail-closed. However good the rules get, something
will always fall through, so what matters is where.

Every rule's examples and counterexamples are executed. A rule whose example it does
not match is a rule that does not do what it says; a rule that matches its own
counterexample is a rule that will fire on ordinary questions until nobody reads it.
"""

from __future__ import annotations

import pytest
from korpus.application.risk import risk_adjusted_thresholds
from korpus.application.risk_rules import RISK_RULES, QueryRisk, classify


@pytest.mark.parametrize(
    "rule,example",
    [(rule, example) for rule in RISK_RULES for example in rule.examples],
    ids=[f"{rule.id}:{i}" for rule in RISK_RULES for i, _ in enumerate(rule.examples)],
)
def test_every_rule_matches_its_own_examples(rule, example: str) -> None:
    risk, matched = classify(example)

    assert risk is rule.risk, f"{example!r} classified {risk} by {matched}"


@pytest.mark.parametrize(
    "rule,counterexample",
    [(rule, text) for rule in RISK_RULES for text in rule.counterexamples],
    ids=[
        f"{rule.id}:not:{i}"
        for rule in RISK_RULES
        for i, _ in enumerate(rule.counterexamples)
    ],
)
def test_no_rule_fires_on_its_own_counterexamples(rule, counterexample: str) -> None:
    """A rule that fires on ordinary questions is a rule operators learn to ignore."""
    _, matched = classify(counterexample)

    assert matched != rule.id, f"{rule.id} fired on {counterexample!r}"


def test_every_rule_carries_at_least_one_example() -> None:
    """An example is the only executable statement of what a pattern is for."""
    bare = [rule.id for rule in RISK_RULES if not rule.examples]

    assert bare == [], bare


def test_every_rule_states_why_it_exists() -> None:
    thin = [rule.id for rule in RISK_RULES if len(rule.rationale.strip()) < 20]

    assert thin == [], thin


def test_rule_ids_are_unique() -> None:
    identifiers = [rule.id for rule in RISK_RULES]

    assert len(identifiers) == len(set(identifiers))


@pytest.mark.parametrize(
    "query",
    [
        "Чи можу я виїхати без письмового підтвердження?",
        "Що робити, якщо командир відсутній?",
        "Am I allowed to release this to a partner unit?",
        "Чи маю я доповідати про це негайно?",
    ],
)
def test_a_rephrased_operational_question_is_still_operational(query: str) -> None:
    """The RAG-009 bypass, stated as the cases that used to get through.

    None of these name an order, a procedure or an obligation. All of them ask whether
    the reader may act, which is what makes a question operational.
    """
    risk, _ = classify(query)

    assert risk is QueryRisk.OPERATIONAL


def test_an_unrecognised_query_is_unclassified_not_standard() -> None:
    """The fail-open direction, closed.

    STANDARD means "we judged this ordinary". UNCLASSIFIED means "we could not judge
    it". Collapsing the second into the first hides which one happened, and gives the
    unknown case the cheapest thresholds in the system.
    """
    risk, matched = classify("Скільки сторінок у додатку?")

    assert risk is QueryRisk.UNCLASSIFIED
    assert matched is None


def test_the_deciding_rule_travels_with_the_class() -> None:
    """A class without its reason is a number the reader has to trust."""
    risk, matched = classify("Чи дозволено виносити документи?")

    assert risk is QueryRisk.OPERATIONAL
    assert matched == "operational.obligation"


def test_operational_outranks_temporal_when_both_apply() -> None:
    """"Which order is current and what do I do" is a question about acting."""
    risk, _ = classify("Яка редакція чинна і що я маю робити?")

    assert risk is QueryRisk.OPERATIONAL


def test_unclassified_costs_more_than_standard() -> None:
    """Not knowing what a question is must not be the cheapest place to land."""
    base = dict(minimum_score=0.2, minimum_query_coverage=0.3, minimum_support_score=0.2)
    standard = risk_adjusted_thresholds(QueryRisk.STANDARD, **base)
    unclassified = risk_adjusted_thresholds(QueryRisk.UNCLASSIFIED, **base)

    assert unclassified.minimum_score > standard.minimum_score
    assert unclassified.minimum_support_score > standard.minimum_support_score
    assert unclassified.minimum_authority > standard.minimum_authority


def test_unclassified_raises_evidence_but_not_relevance() -> None:
    """Coverage is a property of the retrieval, not of the risk class.

    Not knowing how dangerous a question is says nothing about how much of it the
    evidence covers. Raising coverage for the unknown class refused two frozen
    evaluation cases the corpus answers correctly, and the frozen protocol forbids
    editing the dataset to match — so the threshold with no argument behind it moved
    instead. Stated as a test because it is the kind of asymmetry that gets "tidied"
    into symmetry by someone who did not see the evaluation fail.
    """
    base = dict(minimum_score=0.2, minimum_query_coverage=0.3, minimum_support_score=0.2)
    standard = risk_adjusted_thresholds(QueryRisk.STANDARD, **base)
    unclassified = risk_adjusted_thresholds(QueryRisk.UNCLASSIFIED, **base)

    assert unclassified.minimum_query_coverage == standard.minimum_query_coverage


def test_unclassified_costs_less_than_operational() -> None:
    """Scoring the unknown at the strictest setting would refuse most ordinary
    questions and teach operators that refusals mean nothing."""
    base = dict(minimum_score=0.2, minimum_query_coverage=0.3, minimum_support_score=0.2)
    operational = risk_adjusted_thresholds(QueryRisk.OPERATIONAL, **base)
    unclassified = risk_adjusted_thresholds(QueryRisk.UNCLASSIFIED, **base)

    assert unclassified.minimum_score < operational.minimum_score
    assert unclassified.minimum_authority < operational.minimum_authority


def test_the_corpus_of_examples_is_large_enough_to_mean_something() -> None:
    """Two examples across five rules would satisfy every test above and prove little."""
    total = sum(len(rule.examples) + len(rule.counterexamples) for rule in RISK_RULES)

    assert total >= 15, total
