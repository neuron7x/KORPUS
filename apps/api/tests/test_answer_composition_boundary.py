"""Negative controls for one-profile composition and adapter identity."""

from unittest.mock import Mock

import pytest
from korpus import answer_composition
from korpus.api import dependencies
from korpus.application.cache import EvidenceQueryCache
from korpus.application.calibration import CalibrationProfile
from korpus.application.policy import PolicyEngine
from korpus.config import Settings

from apps.api.tests.test_calibration import profile


def test_answer_and_ranking_load_one_calibration(monkeypatch):
    first = profile(profile_id="first-profile", minimum_score=0.41)
    second = profile(profile_id="second-profile", minimum_score=0.72)
    loader = Mock(side_effect=[first, second])
    monkeypatch.setattr(CalibrationProfile, "load", loader)
    settings = Settings().model_copy(update={"answer_policy_mode": "calibrated"})
    service = dependencies.get_answer_service(
        Mock(), PolicyEngine(), settings, EvidenceQueryCache(), None
    )
    assert loader.call_count == 1
    assert (
        service.answer_policy.calibration_id
        == service.retriever.configuration_id
        == "first-profile"
    )
    assert service.answer_policy.minimum_score == 0.41
    assert service.retriever.delegate.parameters == first.bm25_parameters
    assert service.retriever.delegate.weights == first.retrieval_weights


class FalseyAdapter:
    def __bool__(self):
        return False


@pytest.mark.parametrize(
    "parameter,factory",
    [
        ("query_planner", "build_query_planner"),
        ("answer_composer", "build_answer_composer"),
    ],
)
def test_supplied_adapter_identity_survives_false_truth_value(monkeypatch, parameter, factory):
    adapter = FalseyAdapter()
    replacement = Mock(side_effect=AssertionError("injected adapter must not be replaced"))
    monkeypatch.setattr(answer_composition, factory, replacement)
    service = dependencies.get_answer_service(
        Mock(),
        PolicyEngine(),
        Settings(),
        EvidenceQueryCache(),
        None,
        **{parameter: adapter},
    )
    assert getattr(service, parameter) is adapter
    replacement.assert_not_called()


def test_absent_adapters_still_use_existing_factories(monkeypatch):
    planner, composer = Mock(), Mock()
    monkeypatch.setattr(answer_composition, "build_query_planner", lambda _: planner)
    monkeypatch.setattr(answer_composition, "build_answer_composer", lambda _: composer)
    service = dependencies.get_answer_service(
        Mock(), PolicyEngine(), Settings(), EvidenceQueryCache(), None
    )
    assert service.query_planner is planner
    assert service.answer_composer is composer
    assert service.answer_policy.calibration_id == "development-unvalidated"
    assert service.retriever.configuration_id == "development-default-ranking-v5"


def test_composition_factory_is_usable_without_http_dependency_injection():
    from korpus.answer_composition import build_answer_service

    service = build_answer_service(Mock(), PolicyEngine(), Settings(), EvidenceQueryCache(), None)
    assert service.query_planner is None
    assert service.answer_composer is None
    assert service.retriever.delegate.candidate_budget == Settings().retrieval_candidate_budget
