from korpus.application.answer_query import AnswerPolicy
from korpus.application.risk import QueryRisk, classify_query_risk, risk_adjusted_thresholds
from korpus.domain.models import AuthorityClass


def test_query_risk_classifier_is_deterministic_and_conservative():
    assert classify_query_risk("Який порядок дій визначає наказ?") is QueryRisk.OPERATIONAL
    assert classify_query_risk("Яка редакція чинна станом на сьогодні?") is QueryRisk.TEMPORAL
    assert classify_query_risk("Що містить документ?") is QueryRisk.STANDARD


def test_risk_thresholds_are_monotone():
    standard = risk_adjusted_thresholds(
        QueryRisk.STANDARD, minimum_score=0.2, minimum_query_coverage=0.3, minimum_support_score=0.2
    )
    temporal = risk_adjusted_thresholds(
        QueryRisk.TEMPORAL, minimum_score=0.2, minimum_query_coverage=0.3, minimum_support_score=0.2
    )
    operational = risk_adjusted_thresholds(
        QueryRisk.OPERATIONAL,
        minimum_score=0.2,
        minimum_query_coverage=0.3,
        minimum_support_score=0.2,
    )
    assert standard.minimum_score < temporal.minimum_score < operational.minimum_score
    assert standard.minimum_authority < temporal.minimum_authority < operational.minimum_authority


def test_answer_policy_exposes_no_authority_bypass():
    policy = AnswerPolicy(0.1, 0.1, 0.1, "test")
    assert AuthorityClass.UNKNOWN.value == "unknown"
    assert policy.max_claims == 4
