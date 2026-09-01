import pytest
from korpus.application.client_bootstrap import build_client_bootstrap
from korpus.application.policy import KNOWN_PERMISSIONS, PolicyEngine
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity

from apps.api.tests.conftest import set_identity


def _identity(*roles: str) -> Identity:
    return Identity(
        subject="bootstrap-user",
        roles=frozenset(roles),
        clearance=AccessTier.AUTHENTICATED,
        corpora=frozenset({"public"}),
    )


def test_bootstrap_expands_admin_wildcard_to_closed_permission_vocabulary():
    projected = build_client_bootstrap(
        _identity("admin"), Settings(environment="test", auth_mode="disabled"), PolicyEngine()
    )
    assert projected.effective_permissions == tuple(sorted(KNOWN_PERMISSIONS))
    assert "*" not in projected.effective_permissions


def test_bootstrap_projects_runtime_capabilities_without_client_reconstruction(tmp_path):
    key = tmp_path / "offline.key"
    key.write_bytes(b"k" * 32)
    projected = build_client_bootstrap(
        _identity("user"),
        Settings(
            environment="test",
            auth_mode="disabled",
            browser_auth_enabled=False,
            subscription_required=True,
            offline_pack_enabled=True,
            offline_pack_signing_key_file=key,
            ingestion_mode="durable_async",
        ),
        PolicyEngine(),
    )
    assert projected.release == "v0.9.7"
    assert projected.api_version == "v1"
    assert projected.effective_permissions == ("answer:read", "document:list")
    assert projected.capabilities.model_dump() == {
        "browser_auth_enabled": False,
        "subscription_required": True,
        "offline_pack_enabled": True,
        "ingestion_mode": "durable_async",
    }


def test_bootstrap_route_returns_same_identity_and_effective_permissions(client):
    set_identity(client, _identity("auditor"))
    response = client.get("/v1/client/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["identity"]["subject"] == "bootstrap-user"
    assert payload["effective_permissions"] == ["audit:read", "audit:verify", "document:list"]
    assert payload["release"] == "v0.9.7"


from apps.api.tests.helpers import approve, ingest_text  # noqa: E402


def test_the_client_is_told_the_rule_not_only_the_verdict(client, admin_identity) -> None:
    """Клієнт діставав `answered` і числа, але НЕ межу, з якою сервер їх порівняв.

    Виміряно 01.09.2026 на живому розгортанні: «Яка столиця Бразилії?» дістало
    `answered` із `query_coverage` рівно 0.5 — на самій межі, — тоді як своє
    питання дало 1.0. Вісь `boundary_foreign` тримає підлогу 0.75, тобто чужі
    питання впускаються ЗА ПОБУДОВОЮ; відрізнити їх може лише той, хто бачить
    запас над порогом. Без порога «0.5» нечитабельне.
    """
    settings = client.app.state.settings if hasattr(client.app.state, "settings") else None
    payload = client.get("/v1/client/bootstrap").json()
    admission = payload["admission"]

    assert set(admission) == {
        "min_retrieval_score",
        "min_query_coverage",
        "min_support_score",
    }
    for value in admission.values():
        assert isinstance(value, int | float)
        assert 0.0 <= float(value) <= 1.0
    if settings is not None:
        # Те саме поле, а не друге оголошення: копія розійшлася б мовчки.
        assert admission["min_query_coverage"] == settings.min_query_coverage
        assert admission["min_retrieval_score"] == settings.min_retrieval_score
        assert admission["min_support_score"] == settings.min_support_score


def test_the_published_threshold_is_the_one_the_answer_path_applies(client) -> None:
    """Дуал, і він ПОВЕДІНКОВИЙ, а не структурний.

    Перша версія звіряла віддане число з `get_settings()` — глобальним кешем
    процесу, — і впала: набір підіймає застосунок із власними `Settings`
    (`min_query_coverage=0.15`), а глобальний кеш каже 0.5. Тобто вона порівняла
    ДВА РІЗНІ оголошення й повідомила про це як про розбіжність правила. Рівно та
    форма, що коштувала сьогодні пів дня на канонічній гілці.

    Тому питається не «чи збігаються числа», а «чи це число описує ту межу, яку
    сервер справді застосував»: відповідь, допущена сервером, мусить мати
    покриття НЕ НИЖЧЕ за оголошений поріг.
    """
    admission = client.get("/v1/client/bootstrap").json()["admission"]
    result = ingest_text(client, text="Вартовий підпорядковується начальникові варти.")
    approve(client, result["version"]["id"])

    answer = client.post("/v1/answers", json={"text": "Кому підпорядковується вартовий?"}).json()
    if answer["status"] != "answered":
        pytest.skip("на цій фікстурі відповідь не допущено; поріг перевіряти нема на чому")
    assert answer["query_coverage"] >= admission["min_query_coverage"], (
        "сервер допустив відповідь нижче за поріг, який сам оголосив клієнтові"
    )
