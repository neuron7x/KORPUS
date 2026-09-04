"""Відмови налаштувань і готовності, яких не викликав жоден прогін.

Вимір покриття гілок 04.09.2026. Спільне в усіх: вони стоять між оголошенням і
роботою. Налаштування, що прийняло невідому роль або невідомий транспорт, не
падає — воно ПРАЦЮЄ не так, як написано; каблучка, що мовчки перезаписала активний
ключ, робить підпис і перевірку різними речами під одним ім'ям.
"""

from __future__ import annotations

import pathlib
import time
from types import SimpleNamespace

import pytest
from korpus.application.cache import EvidenceQueryCache
from korpus.application.declared_subject import declared_subject_documents
from korpus.application.semantic_readiness import failure_reason, semantic_status
from korpus.config import Settings


def _settings(tmp_path: pathlib.Path, **changes: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "schema_mode": "auto",
        "database_url": f"sqlite:///{tmp_path / 'test.db'}",
        "object_root": tmp_path / "objects",
        "audit_anchor_path": tmp_path / "audit-anchor.json",
        "audit_hmac_key": "test-audit-key",
        "auth_mode": "dev",
        "dev_mode_acknowledgement": "I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        "bind_host": "127.0.0.1",
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


def test_an_unknown_runtime_role_is_refused_at_construction(tmp_path: pathlib.Path) -> None:
    """Роль визначає, ЩО процес робить. Невідома роль не падає — вона працює не тим."""
    with pytest.raises(ValueError, match="runtime_role must be one of"):
        _settings(tmp_path, runtime_role="сторож")


def test_an_unknown_database_transport_is_refused_at_construction(
    tmp_path: pathlib.Path,
) -> None:
    """Транспорт бази — це те, чим ідуть облікові дані. Невідомий не має типової поведінки."""
    with pytest.raises(ValueError, match="database_transport must be"):
        _settings(tmp_path, database_transport="ssh_tunnel")


def test_known_roles_and_transports_are_accepted(tmp_path: pathlib.Path) -> None:
    """Негативне плече: перевірки вище не сміють бути завжди-червоними."""
    assert _settings(tmp_path, runtime_role="api").runtime_role == "api"
    assert (
        _settings(tmp_path, database_transport="cloud_sql_socket").database_transport
        == "cloud_sql_socket"
    )


def test_a_background_role_may_not_use_dev_authentication(tmp_path: pathlib.Path) -> None:
    """Перехресне правило, знайдене цим прогоном: роль і спосіб входу пов'язані.

    `worker` сам по собі законний, а `auth_mode="dev"` сам по собі законний — разом
    вони не законні. Перевірка одного поля цього не побачила б, і саме тому вона
    живе не у валідаторі поля.
    """
    with pytest.raises(ValueError, match="background runtime roles cannot use dev"):
        _settings(tmp_path, runtime_role="worker")


def test_a_verification_key_may_not_reuse_the_active_key_id(tmp_path: pathlib.Path) -> None:
    """Мовчазне перезаписування активного ключа — та сама вада, яку каблучка лікує.

    Підпис і перевірка стали б різними речами під одним ім'ям, і жоден читач
    журналу не побачив би підміни.
    """
    key_file = tmp_path / "old.key"
    key_file.write_bytes(b"o" * 32)
    settings = _settings(
        tmp_path,
        audit_key_id="k1",
        audit_verification_key_files={"k1": str(key_file)},
    )
    with pytest.raises(ValueError, match="той самий ід"):
        settings.resolved_audit_keyring()


def test_verification_keys_with_distinct_ids_join_the_ring(tmp_path: pathlib.Path) -> None:
    """Ключі, здатні ще перевіряти після заміни, лишаються в каблучці — але як інші."""
    key_file = tmp_path / "old.key"
    key_file.write_bytes(b"o" * 32)
    settings = _settings(
        tmp_path,
        audit_key_id="k2",
        audit_verification_key_files={"k1": str(key_file)},
    )
    ring = settings.resolved_audit_keyring()
    assert ring.active_key_id == "k2"
    assert set(ring.keys) == {"k1", "k2"}


def test_an_empty_verification_map_leaves_only_the_active_key(tmp_path: pathlib.Path) -> None:
    """Третє плече: порожнє відображення не має додавати нічого й не має падати."""
    ring = _settings(tmp_path, audit_key_id="k1").resolved_audit_keyring()
    assert set(ring.keys) == {"k1"}


# ───────────────────────────── готовність ─────────────────────────────


@pytest.mark.parametrize(
    "source", [None, SimpleNamespace(corpus_governance=None)]
)
def test_semantic_is_not_ready_when_there_is_nothing_to_ask(source: object) -> None:
    """Увімкнена семантика без джерела — НЕ готова, і не «готова за замовчуванням».

    Повернути True тут означало б оголосити придатним пошук, якого немає чим
    виконати: класична підміна невідомого дозволом.
    """
    assert semantic_status(True, source) == (False, None)


def test_semantic_that_is_switched_off_is_ready_by_definition() -> None:
    """Негативне плече: вимкнена спроможність не може бути «не готовою»."""
    assert semantic_status(False, None) == (True, None)


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({"object_store": False, "schema": True, "semantic": True}, "object_store"),
        ({"object_store": True, "schema": False, "semantic": True}, "schema"),
        ({"object_store": True, "schema": True, "semantic": False}, "semantic_index"),
        ({"object_store": True, "schema": True, "semantic": True}, "audit_backlog"),
    ],
)
def test_the_first_unmet_prerequisite_is_the_named_reason(
    flags: dict[str, bool], expected: str
) -> None:
    """Причина одна й найглибша: сховище перед схемою, схема перед індексом.

    Назвати верхню причину при зламаному сховищі означало б послати читача
    лагодити наслідок.
    """
    assert failure_reason(**flags) == expected


# ────────────────────────── оголошений предмет ──────────────────────────


def _item(title: object, document_id: object) -> SimpleNamespace:
    return SimpleNamespace(document=SimpleNamespace(canonical_title=title, id=document_id))


def test_evidence_without_a_title_or_an_id_is_skipped_not_counted() -> None:
    """Документ без заголовка не оголошує предмета; без ід — його нікому приписати.

    Порожній ключ у відображенні став би «документом», якого немає, і ранжування
    за точністю предмета розподіляло б вагу на ніщо.
    """
    title = "Обов'язки: командира механізованого взводу (Статут внутрішньої служби)"
    evidence = [
        _item(None, "d1"),
        _item("", "d2"),
        _item(title, ""),
        _item(title, "d3"),
    ]
    # Заголовок `None` мусить бути ВІДКИНУТИЙ до розбору: якби він потрапив у
    # відображення, розпізнавач предмета отримав би None замість рядка.
    result = declared_subject_documents(
        "Які обов'язки має командир механізованого взводу?", evidence
    )
    assert dict(result) == {"d3": len("командира механізованого взводу")}
    assert "" not in result
    assert "d1" not in result and "d2" not in result


# ───────────────────────────────── кеш ─────────────────────────────────


@pytest.mark.parametrize(("entries", "ttl"), [(0, 30.0), (-1, 30.0), (512, 0.0), (512, -1.0)])
def test_cache_limits_must_be_positive(entries: int, ttl: float) -> None:
    """Кеш на нуль записів або з нульовим життям — не кеш, а мовчазне вимкнення."""
    with pytest.raises(ValueError, match="cache limits must be positive"):
        EvidenceQueryCache(maximum_entries=entries, ttl_seconds=ttl)


def test_an_expired_entry_is_dropped_rather_than_left_to_rot() -> None:
    """Прострочений запис не просто не віддається — він ВИЛУЧАЄТЬСЯ.

    Інакше кеш накопичував би мертві ключі до самого витіснення, і межа розміру
    рахувала б те, що вже ніколи не буде віддане.
    """
    cache = EvidenceQueryCache(maximum_entries=4, ttl_seconds=0.01)
    cache.put("k", [])
    assert cache.stats().entries == 1
    time.sleep(0.05)
    assert cache.get("k") is None
    # Спостерігається саме ВИЛУЧЕННЯ, а не лише «не віддано»: без нього мертвий ключ
    # лишався б у межі розміру й витісняв би живі.
    assert cache.stats().entries == 0
