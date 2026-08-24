"""Non-interference is measured against the store, not against a hand-written list.

Destruction stage, 2026-08-03: the leakage metric compared answers against markers a
dataset row happened to declare, and 2 of 30 rows declared any. A real
``training → PUBLIC`` disclosure passed with `30/30` and `leakage_failures=0`.

These tests state the two halves separately: that the withheld set is non-empty for a
subject who cannot see part of the corpus (the denominator exists), and that an answer
carrying withheld material is recognised (the numerator can move).
"""

from __future__ import annotations

import hashlib
from datetime import date

from fastapi.testclient import TestClient
from korpus.application.noninterference import leaked_material, withheld_material
from korpus.domain.models import Citation, Identity

from apps.api.tests.helpers import approve, ingest_text

AS_OF = date(2026, 8, 4)
RESTRICTED_MARKER = "ОБМЕЖЕНИЙ"


def _seed(client: TestClient) -> dict[str, str]:
    public = ingest_text(client, title="Публічний наказ", text="Журнал ведеться щодоби.")
    approve(client, public["version"]["id"])
    restricted = ingest_text(
        client,
        title="Обмежений наказ",
        corpus_id="restricted-demo",
        access_tier=3,
        classification="restricted",
        text=f"Маркер {RESTRICTED_MARKER} доступний лише в обмеженому корпусі.",
    )
    approve(client, restricted["version"]["id"])
    return {
        "public_version": str(public["version"]["id"]),
        "restricted_version": str(restricted["version"]["id"]),
    }


def test_the_withheld_set_is_not_empty_for_a_subject_who_cannot_see_everything(
    client: TestClient, admin_identity: Identity, public_identity: Identity
) -> None:
    seeded = _seed(client)
    repository = client.app.state.repository

    withheld = withheld_material(repository, admin_identity, public_identity, AS_OF)

    assert withheld, "a public reader must have something withheld in this corpus"
    assert any(item.version_id == seeded["restricted_version"] for item in withheld)
    assert all(item.version_id != seeded["public_version"] for item in withheld)


def test_the_withheld_set_is_empty_for_the_reference_subject(
    client: TestClient, admin_identity: Identity
) -> None:
    """The denominator is honest in the other direction too: nothing is withheld."""
    _seed(client)
    repository = client.app.state.repository

    assert withheld_material(repository, admin_identity, admin_identity, AS_OF) == []


def test_an_answer_quoting_withheld_text_is_recognised_as_a_leak(
    client: TestClient, admin_identity: Identity, public_identity: Identity
) -> None:
    _seed(client)
    repository = client.app.state.repository
    withheld = withheld_material(repository, admin_identity, public_identity, AS_OF)
    target = next(item for item in withheld if RESTRICTED_MARKER in item.text)
    citation = Citation(
        document_id=target.document_id,
        version_id=target.version_id,
        span_id=target.span_id,
        title="Обмежений наказ",
        revision="1.0",
        quote=target.text,
        quote_start=0,
        quote_end=len(target.text),
        quote_hash=hashlib.sha256(target.text.encode("utf-8")).hexdigest(),
        source_hash="0" * 64,
    )

    reasons = leaked_material("{}", [citation], withheld)

    assert any(reason.startswith("withheld_span_quoted:") for reason in reasons), reasons


def test_an_answer_naming_a_withheld_identifier_is_recognised_as_a_leak(
    client: TestClient, admin_identity: Identity, public_identity: Identity
) -> None:
    """Naming a span the reader may not see already discloses that it exists."""
    _seed(client)
    repository = client.app.state.repository
    withheld = withheld_material(repository, admin_identity, public_identity, AS_OF)
    target = withheld[0]

    reasons = leaked_material(f'{{"span_id": "{target.span_id}"}}', [], withheld)

    assert any(reason.startswith("withheld_span_identifier:") for reason in reasons), reasons


def test_a_clean_answer_reports_no_reasons(
    client: TestClient, admin_identity: Identity, public_identity: Identity
) -> None:
    """The negative control: the check must not fire on an answer that leaked nothing."""
    _seed(client)
    repository = client.app.state.repository
    withheld = withheld_material(repository, admin_identity, public_identity, AS_OF)

    assert leaked_material('{"text": "Журнал ведеться щодоби."}', [], withheld) == []
