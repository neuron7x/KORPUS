"""Anchor delivery has to keep up with the rate audit events are written.

Delivery used to walk the outbox one row per iteration: select the oldest pending,
write it, mark it, repeat. With the shipped settings — 64 rows every 2 seconds — that
is about 32 deliveries a second against an append rate measured at ~480/s on
PostgreSQL, so the backlog grew without bound under load. Probed 2026-08-05: 1500
appends, two full reconcile cycles after the load stopped, 882 checkpoints still
undelivered.

The consequence is not a slow queue. The external anchor is the one mechanism that
notices a database rolled back to an older state, and an anchor 882 events behind the
head describes a system that no longer exists — while every gate stays green, because
the chain itself is intact.

The anchor holds a single value and `AnchorStore.write` is monotonic, so an older
checkpoint carries nothing a newer one does not: delivering the newest and closing the
ones it supersedes is one write per pass regardless of backlog.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from korpus.domain.models import Identity
from sqlalchemy import text

from apps.api.tests.conftest import privileged_connection


def _make_backlog(client: TestClient, repository, admin_identity: Identity, count: int) -> None:
    """Undo delivery so the outbox looks like it does under sustained load.

    `append_audit` opportunistically delivers one checkpoint after each commit, and
    under a test's serial writes that keeps the outbox empty — which is exactly the
    condition this test must not run in.
    """

    for index in range(count):
        repository.append_audit(admin_identity, "backlog.probe", "test", str(index), {"i": index})
    with privileged_connection(client) as connection:
        connection.execute(text("UPDATE audit_anchor_outbox SET delivered_at = NULL"))
    repository.anchor_store.reset()
    repository.anchor_store.write(0, "0" * 64)


def test_one_pass_clears_a_backlog_larger_than_the_batch(
    client: TestClient, admin_identity: Identity
) -> None:
    repository = client.app.state.repository
    _make_backlog(client, repository, admin_identity, 120)
    assert repository.verify_audit().anchor_pending == 120

    repository.reconcile_audit_anchor(limit=64)

    assert repository.verify_audit().anchor_pending == 0, (
        "one pass must bring the anchor to the head: an older checkpoint carries "
        "nothing a newer one does not"
    )


def test_delivery_reports_how_many_checkpoints_it_closed(
    client: TestClient, admin_identity: Identity
) -> None:
    """The count feeds the backlog metric, so it must mean rows, not passes."""
    repository = client.app.state.repository
    _make_backlog(client, repository, admin_identity, 10)

    closed = repository.reconcile_audit_anchor()

    assert closed == 10


def test_an_empty_outbox_closes_nothing_when_the_anchor_is_already_at_the_head(
    client: TestClient, admin_identity: Identity
) -> None:
    """Негативний контроль: наздоганяти нема чого, тож і рядків не закривається."""
    repository = client.app.state.repository
    repository.append_audit(admin_identity, "backlog.probe", "test", "1", {"i": 1})
    repository.reconcile_audit_anchor()

    assert repository.reconcile_audit_anchor() == 0
    assert repository.verify_audit().anchor_pending == 0


def test_an_anchor_behind_the_head_catches_up_even_with_an_empty_outbox(
    client: TestClient, admin_identity: Identity
) -> None:
    """Стан, у якому якір розгортання простояв добу, і жоден гейт про це не сказав.

    Черга каже «що ще не доставлено», і це твердження ГЛОБАЛЬНЕ, тоді як доставка є
    властивістю ПАРИ (контрольна точка, призначення). Два процеси з різними шляхами
    якоря ділили один прапорець: хто перший звів чергу, той її й забрав, а другий
    діставав порожній добір, повертав нуль і НЕ ПРОБУВАВ писати.

    Виміряно 31.08.2026: якір стояв на 1024 із 7223 добу, черга була порожня, ланцюг
    цілий, усі гейти зелені. Мовчання, а не помилка.

    Тому ціль реконсиляції береться з ГОЛОВИ журналу: кожне призначення доганяє її
    самостійно, і спорожнена кимось черга нікого не зупиняє.
    """
    repository = client.app.state.repository
    for index in range(3):
        repository.append_audit(admin_identity, "backlog.probe", "test", str(index), {"i": index})
    repository.reconcile_audit_anchor()
    assert repository.verify_audit().anchor_pending == 0

    # Інший процес зі СВОЇМ шляхом якоря звів чергу: рядки позначені доставленими,
    # а ЦЕЙ якір лишився позаду.
    repository.anchor_store.reset()
    repository.anchor_store.write(0, "0" * 64)
    with privileged_connection(client) as connection:
        connection.execute(text("UPDATE audit_anchor_outbox SET delivered_at = CURRENT_TIMESTAMP"))
    assert repository.verify_audit().anchor_pending > 0, "передумова тесту: якір відстав"

    repository.reconcile_audit_anchor()

    assert repository.verify_audit().anchor_pending == 0, (
        "порожня черга не сміє означати «наздоганяти нема чого»: вона глобальна, "
        "а відставання — властивість цього призначення"
    )
