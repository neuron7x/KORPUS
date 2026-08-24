"""Boundary cases whose short-circuit paths are production configuration contracts."""

from types import SimpleNamespace

import pytest
from korpus.application.coverage_policy import relative_source_path, risk_weight
from korpus.application.embedding_contracts import (
    counters_within_total,
    validate_embedding_coverage,
)
from korpus.billing_config_policy import validate_billing_settings
from korpus.domain.operational_competency import CompetencyFramework
from pydantic import ValidationError


def _billing(**updates: object) -> SimpleNamespace:
    values = {
        "liqpay_public_key": "",
        "resolved_liqpay_private_key": "",
        "liqpay_signature_algorithm": "sha3_256",
        "billing_public_base_url": "https://example.test",
        "billing_plan_code": "",
        "billing_plan_price_minor": None,
        "billing_plan_currency": "UAH",
        "billing_plan_interval": "monthly",
        "billing_plan_corpus_set": frozenset(),
    }
    return SimpleNamespace(**(values | updates))


def test_billing_absence_is_valid_but_each_partial_liqpay_configuration_is_refused() -> None:
    validate_billing_settings(_billing())
    with pytest.raises(ValueError, match="both public and private"):
        validate_billing_settings(_billing(liqpay_public_key="public"))
    with pytest.raises(ValueError, match="both public and private"):
        validate_billing_settings(_billing(resolved_liqpay_private_key="private"))


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"liqpay_signature_algorithm": "md5"}, "signature algorithm"),
        ({"billing_public_base_url": ""}, "billing_public_base_url"),
        ({"billing_public_base_url": "http://remote.test"}, "billing_public_base_url"),
    ],
)
def test_complete_liqpay_configuration_still_refuses_each_unsafe_field(
    updates: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_billing_settings(
            _billing(
                liqpay_public_key="public",
                resolved_liqpay_private_key="private",
                **updates,
            )
        )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({}, "price_minor"),
        ({"billing_plan_price_minor": 100, "billing_plan_currency": "GBP"}, "currency"),
        ({"billing_plan_price_minor": 100, "billing_plan_interval": "weekly"}, "interval"),
        ({"billing_plan_price_minor": 100}, "at least one corpus"),
    ],
)
def test_sellable_plan_refuses_each_incomplete_dimension(
    updates: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_billing_settings(_billing(billing_plan_code="plan", **updates))


def test_fully_specified_provider_and_plan_pass_together() -> None:
    validate_billing_settings(
        _billing(
            liqpay_public_key="public",
            resolved_liqpay_private_key="private",
            billing_plan_code="plan",
            billing_plan_price_minor=100,
            billing_plan_corpus_set=frozenset({"public"}),
        )
    )


@pytest.mark.parametrize("duplicate", ["roles", "tasks", "competencies"])
def test_framework_refuses_duplicate_identity_in_every_namespace(duplicate: str) -> None:
    framework = {
        "id": "framework",
        "revision": "1",
        "roles": [{"id": "role", "title": "Defined role", "task_ids": ["task"]}],
        "tasks": [
            {
                "id": "task",
                "statement": "Defined task",
                "conditions": "Defined conditions",
                "standard": "Defined standard",
                "competency_ids": ["competency"],
            }
        ],
        "competencies": [{"id": "competency", "statement": "Defined competency"}],
    }
    framework[duplicate] = [*framework[duplicate], framework[duplicate][0]]
    label = {"roles": "role", "tasks": "task", "competencies": "competency"}[duplicate]
    with pytest.raises(ValidationError, match=f"{label} ids must be unique"):
        CompetencyFramework.model_validate(framework)


def test_coverage_paths_handle_relative_windows_and_absolute_forms() -> None:
    assert relative_source_path("security/auth.py") == "security/auth.py"
    assert relative_source_path(r"C:\repo\apps\api\src\korpus\security\auth.py") == (
        "security/auth.py"
    )
    assert relative_source_path("/repo/apps/api/src/korpus/domain/models.py") == (
        "domain/models.py"
    )
    assert risk_weight("domain/models.py", {}) == 1.0
    assert risk_weight("security/auth.py", {"security/": 3.0, "security/auth": 5.0}) == 5.0


def test_embedding_counter_contract_covers_short_circuit_boundaries() -> None:
    assert counters_within_total(3, 0, 3)
    assert not counters_within_total(-1, 0)
    assert not counters_within_total(3, -1)
    assert not counters_within_total(3, 4)
    assert not counters_within_total(3, 1.0)
    with pytest.raises(ValueError, match="non-empty"):
        validate_embedding_coverage(" ", 8, 0, 0, 0, 0)
    with pytest.raises(ValueError, match="at least 8"):
        validate_embedding_coverage("model", 7, 0, 0, 0, 0)
    with pytest.raises(ValueError, match="bounded by total"):
        validate_embedding_coverage("model", 8, 1, 2, 0, 0)
    validate_embedding_coverage("model", 8, 3, 1, 1, 1)
