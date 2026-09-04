"""Останні гілки без прогону: навчання контролера, підписант пакета, клієнт вбудовувань.

Вимір покриття гілок 04.09.2026. Спільне: усі ці шляхи виконуються рідко або лише
на межі — коли даних замало, коли ключ не того типу, коли клієнта не передали. Саме
тому їх ніхто не бачив, і саме тому вони мусять бути перевірені: рідкісний шлях, що
не працює, виявляється в найгіршу хвилину.
"""

from __future__ import annotations

import math
import pathlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from korpus.application.controller_profile import RuleCondition
from korpus.application.pec_training_model import TrainingRow, _candidates, _matches
from korpus.application.pec_training_validation import (
    grouped_folds,
    nested_group_validation,
    select_hyperparameters,
)
from korpus.application.subscriptions import SubscriptionService
from korpus.domain.tenancy import SubscriptionRecord, SubscriptionStatus
from korpus.infrastructure.embedding_provider import HttpEmbeddingProvider
from korpus.infrastructure.offline_pack_signer import Ed25519OfflinePackSigner

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


# ───────────────────────────── передплати ─────────────────────────────


def _subscription(account_id: object, **changes: object) -> SubscriptionRecord:
    values: dict[str, object] = {
        "account_id": account_id,
        "plan_id": uuid4(),
        "provider": "liqpay",
        "status": SubscriptionStatus.ACTIVE,
        "current_period_start": NOW - timedelta(days=1),
        "current_period_end": NOW + timedelta(days=1),
    }
    values.update(changes)
    return SubscriptionRecord(**values)  # type: ignore[arg-type]


def _service(rows: list[SubscriptionRecord]) -> SubscriptionService:
    store = SimpleNamespace(list_subscriptions=lambda account_id: rows)
    return SubscriptionService(store, SimpleNamespace(), SimpleNamespace(name="liqpay"))  # type: ignore[arg-type]


def test_an_account_with_no_subscriptions_has_none_active() -> None:
    """Порожній перелік — це «немає активної», а не помилка й не перша-ліпша."""
    assert _service([]).active_subscription(uuid4(), now=NOW) is None


def test_an_expired_subscription_is_skipped_and_the_active_one_is_found() -> None:
    """Перебір мусить ПРОПУСКАТИ неактивні, а не спинятись на першій-ліпшій.

    Рядок, що каже ACTIVE навіки, лишається після зламаного вебхука; саме тому
    перевіряється ще й період. Тут прострочена йде першою — якби цикл віддавав
    перший елемент, він віддав би її.
    """
    account = uuid4()
    expired = _subscription(account, current_period_end=NOW - timedelta(days=1))
    live = _subscription(account)
    found = _service([expired, live]).active_subscription(account, now=NOW)
    assert found is not None
    assert found.id == live.id


def test_when_every_subscription_is_inactive_the_answer_is_none() -> None:
    """Негативне плече: цикл, що перебрав усе й нічого не знайшов, каже «немає»."""
    account = uuid4()
    rows = [
        _subscription(account, current_period_end=NOW - timedelta(days=1)),
        _subscription(account, status=SubscriptionStatus.CANCELED),
    ]
    assert _service(rows).active_subscription(account, now=NOW) is None


# ────────────────────────── перевірка навчання ──────────────────────────


def _row(group: str, score: float, label: str) -> TrainingRow:
    return TrainingRow(
        query_id=f"q-{group}-{score}", group_id=group, features={"top1_score": score}, label=label
    )


@pytest.mark.parametrize("folds", [1, 0, -3])
def test_grouped_validation_refuses_fewer_than_two_folds(folds: int) -> None:
    """Одна складка не є перевіркою: модель оцінювалась би на тому, чим навчалась."""
    with pytest.raises(ValueError, match="at least two folds"):
        grouped_folds([_row("g1", 0.5, "BASELINE")], folds=folds)


def test_hyperparameter_selection_refuses_when_no_fold_could_be_scored() -> None:
    """Жодної оціненої складки — це «підстав немає», а не «беремо найкраще з нічого».

    `max([])` кинув би ValueError десь усередині, і причиною стала б порожня
    послідовність, а не «даних для вибору замало».
    """
    with pytest.raises(ValueError, match="insufficient grouped data"):
        select_hyperparameters([_row("g1", 0.5, "BASELINE")])


def test_nested_validation_skips_empty_outer_splits_instead_of_failing() -> None:
    """Групування за хешем може лишити складку порожньою; це не привід впасти.

    Порожню зовнішню складку пропускають, і оцінка будується на тих, що є, —
    інакше випадковий розподіл груп вирішував би, чи взагалі буде вимір.
    """
    rows = [_row(f"g{index}", 0.1 * index, "BASELINE") for index in range(3)]
    result = nested_group_validation(rows, outer_folds=5)
    assert isinstance(result, dict)


# ─────────────────────────── модель навчання ───────────────────────────


@pytest.mark.parametrize("actual", [math.inf, -math.inf, math.nan])
def test_an_ordered_comparison_against_a_non_finite_value_is_false(actual: float) -> None:
    """Нескінченне значення ознаки не порівнюють — умова просто не справджується."""
    condition = RuleCondition(feature="top1_score", operator="le", value=0.5)
    assert _matches(actual, condition) is False


def test_candidate_conditions_skip_non_string_values_of_a_mixed_feature() -> None:
    """Ознака зі змішаними типами: рядки дають кандидатів, решта пропускається.

    Числовий поріг на ознаці, де є й рядки, був би порівнянням різних шкал;
    мовчазний `str()` над числом зробив би категорію з величини.
    """
    rows = [
        TrainingRow(query_id="q1", group_id="g1", features={"query_risk": "STANDARD"}, label="A"),
        TrainingRow(query_id="q2", group_id="g2", features={"query_risk": 3}, label="B"),
    ]
    produced = list(_candidates(rows))
    values = [c.value for c in produced if c.feature == "query_risk"]
    assert values == ["STANDARD"]


# ──────────────────────────── підписант ────────────────────────────


def test_a_signing_key_that_is_not_ed25519_is_refused(tmp_path: pathlib.Path) -> None:
    """Тип ключа — частина алгоритму підпису, не деталь зберігання.

    RSA-ключ завантажився б, і підпис вийшов би іншого алгоритму під тим самим
    ім'ям: перевіряльник відхилив би його як «зламаний», хоча зламано не його.
    """
    path = tmp_path / "rsa.pem"
    path.write_bytes(
        generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    with pytest.raises(ValueError, match="must be Ed25519"):
        Ed25519OfflinePackSigner.load(path, "pack-key-1")


def test_an_ed25519_key_is_accepted_and_signs(tmp_path: pathlib.Path) -> None:
    """Негативне плече: відмова вище не сміє бути правдою про кожен ключ."""
    path = tmp_path / "ed25519.pem"
    path.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    signer = Ed25519OfflinePackSigner.load(path, "pack-key-1")
    assert signer.sign_b64(b"payload")
    assert signer.public_key_b64


# ────────────────────────── клієнт вбудовувань ──────────────────────────


def test_a_provider_without_an_injected_client_builds_and_closes_its_own() -> None:
    """Клієнта не передали — постачальник будує власний і мусить уміти його закрити.

    Незакритий клієнт тримає з'єднання після зупинки: у процесі-воркері це витік,
    який видно лише через години.
    """
    provider = HttpEmbeddingProvider(
        endpoint="https://embeddings.invalid/v1/embeddings", model_id="e5-base", dimensions=8
    )
    assert provider.client is not None
    provider.close()


def test_a_client_that_cannot_be_closed_is_not_an_error() -> None:
    """Впроваджений клієнт може не мати `close` — і це законно.

    Постачальник закриває лише те, що вміє закриватись; виняток тут зробив би
    зупинку процесу залежною від форми чужого об'єкта.
    """
    injected = SimpleNamespace(post=lambda url, json: None, get=lambda url, headers: None)
    provider = HttpEmbeddingProvider(
        endpoint="https://embeddings.invalid/v1/embeddings",
        model_id="e5-base",
        dimensions=8,
        client=injected,  # type: ignore[arg-type]
    )
    provider.close()
