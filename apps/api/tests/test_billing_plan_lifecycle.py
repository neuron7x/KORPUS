"""Plan upsert, retirement and the two subscription fields written on first sight.

`upsert_plan` is the only way a sellable plan reaches the database, and the price a
customer is charged comes from it. Measured on 2026-08-28 only the insert arm had been
taken — the update arm, which is what a price change actually is, had no test.

`list_plans` hides retired plans by default. A retired plan still exists because live
subscriptions reference it; showing it in the catalogue would sell a plan nobody may buy.
"""

from __future__ import annotations

from pathlib import Path

from korpus.application.policy import PolicyEngine
from korpus.domain.tenancy import BillingInterval, PlanRecord, PlanStatus
from korpus.infrastructure.billing_repository import SqlSubscriptionStore
from korpus.infrastructure.repository import SqlRepository


def _store(tmp_path: Path) -> SqlSubscriptionStore:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'plans.db'}",
        "plan-audit-key",
        PolicyEngine(),
        tmp_path / "anchor.json",
    )
    repository.initialize()
    return SqlSubscriptionStore(repository)


def _plan(**changes: object) -> PlanRecord:
    values: dict[str, object] = {
        "code": "standard",
        "name": "Стандарт",
        "status": PlanStatus.ACTIVE,
        "billing_interval": BillingInterval.MONTHLY,
        "price_minor": 49900,
        "currency": "UAH",
        "entitled_corpora": frozenset({"public"}),
    }
    values.update(changes)
    return PlanRecord(**values)  # type: ignore[arg-type]


def test_a_new_plan_is_inserted_and_readable_by_code(tmp_path: Path) -> None:
    """The dual: the update path below is only meaningful if insert works."""
    store = _store(tmp_path)
    stored = store.upsert_plan(_plan())
    assert stored.code == "standard"
    assert store.get_plan_by_code("standard") is not None
    assert store.get_plan(stored.id) is not None


def test_upserting_the_same_code_updates_rather_than_duplicating(tmp_path: Path) -> None:
    """A price change is an update; a second row under one code would be two prices.

    The catalogue is keyed by code, so a duplicate makes which price a customer sees a
    function of row order.
    """
    store = _store(tmp_path)
    store.upsert_plan(_plan())
    store.upsert_plan(_plan(name="Стандарт+", price_minor=59900))

    plans = store.list_plans()
    assert [item.code for item in plans] == ["standard"]
    assert plans[0].price_minor == 59900
    assert plans[0].name == "Стандарт+"


def test_a_retired_plan_leaves_the_catalogue_but_stays_readable(tmp_path: Path) -> None:
    """Live subscriptions reference it, so the row stays; the catalogue must not offer it."""
    store = _store(tmp_path)
    store.upsert_plan(_plan())
    store.upsert_plan(_plan(status=PlanStatus.RETIRED))

    assert store.list_plans() == []
    retired = store.list_plans(include_retired=True)
    assert [item.status for item in retired] == [PlanStatus.RETIRED]
    assert store.get_plan_by_code("standard") is not None


def test_an_unknown_plan_reads_as_absent(tmp_path: Path) -> None:
    from uuid import uuid4

    store = _store(tmp_path)
    assert store.get_plan(uuid4()) is None
    assert store.get_plan_by_code("never-created") is None
