"""Reaching material through a side channel rather than through retrieval.

Retrieval is guarded well: `retrieval_queries` applies clearance, classification,
compartment, currency and supersession, and `test_v5_security_kernel.py` holds it. Every
finding here is a route that reached the same rows *around* that projection, and each was
found by an adversarial review on 2026-08-06 rather than by reading.

The shape they share: a check that asks "does this identity hold the permission" without
asking "is this identity entitled to this document". The permission is a role; the
entitlement is a property of the pair. `IngestionService.transition` already carried a
comment saying exactly that, and the two routes beside it did not do it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from korpus.application.ingestion import ExtractionSettings
from korpus.application.policy import PolicyEngine
from korpus.composition import build_ingestion_service
from korpus.config import Settings
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentCreate,
    Identity,
    ReviewState,
    ReviewTransition,
    VersionCreate,
)
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.main import create_app
from korpus.security.auth import get_identity

RESTRICTED_TEXT = "Дистанція між укриттями має бути не менше 300 метрів.\n"

ADMIN = Identity(
    subject="admin",
    roles=frozenset({"admin"}),
    clearance=AccessTier.RESTRICTED,
    corpora=frozenset({"public", "secret"}),
    compartments=frozenset({"bravo"}),
)
#: Authenticated, holds a review role, and is entitled to none of the material below.
#: `GET /v1/documents` returns an empty list for this identity.
OUTSIDER = Identity(
    subject="outsider",
    roles=frozenset({"reviewer", "curator"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public"}),
)


@pytest.fixture
def restricted(tmp_path: Path):
    """An approved, in-force order in a corpus the outsider does not hold."""
    settings = Settings(
        environment="test",
        auth_mode="disabled",
        database_url=f"sqlite:///{tmp_path / 'oracles.db'}",
        object_root=str(tmp_path / "objects"),
        audit_hmac_key="oracle-test-key",
        audit_anchor_path=str(tmp_path / "anchor.json"),
    )
    app = create_app(settings)
    app.dependency_overrides[get_identity] = lambda: ADMIN
    with TestClient(app) as client:
        service = build_ingestion_service(
            client.app.state.repository,
            LocalObjectStore(tmp_path / "objects"),
            PolicyEngine(),
            ExtractionSettings(False, "ukr"),
        )
        result = service.ingest(
            ADMIN,
            DocumentCreate(
                canonical_title="Секретний наказ",
                corpus_id="secret",
                issuer="Генеральний штаб",
                access_tier=AccessTier.RESTRICTED,
                classification=Classification.RESTRICTED,
                compartments=frozenset({"bravo"}),
            ),
            VersionCreate(
                revision="1",
                authority=AuthorityClass.OFFICIAL_UA,
                publication_date=date(2026, 1, 1),
            ),
            "order.txt",
            "text/plain",
            RESTRICTED_TEXT.encode("utf-8"),
        )
        for state in (
            ReviewState.METADATA_REVIEWED,
            ReviewState.CONTENT_REVIEWED,
            ReviewState.APPROVED,
        ):
            service.transition(
                ADMIN, result.version.id, ReviewTransition(target=state, note="bootstrap review")
            )
        app.dependency_overrides[get_identity] = lambda: OUTSIDER
        yield client, result


def test_the_outsider_cannot_see_the_document_at_all(restricted) -> None:
    """The premise every test below rests on. Without it they prove nothing."""
    client, _ = restricted

    assert client.get("/v1/documents").json() == []


def test_an_unentitled_reviewer_cannot_take_an_order_out_of_force(restricted) -> None:
    """The worst of the family: an integrity attack and a disclosure in one request.

    `POST …/rescission` checked `document:approve` and nothing else, and
    `SqlRepository.rescind_version` selects by version id alone — no corpus, no
    clearance, no classification, no compartment. A reviewer whose document list is
    empty could withdraw a restricted order from force with only its id, and the 200
    handed back the full version record: source hash, source uri, object key, approver,
    dates.

    On PostgreSQL row-level security hid the row and the request 404'd. The control
    therefore existed in one dialect and not the other, which is the same defect this
    repository has now found four times.
    """
    client, result = restricted

    response = client.post(
        f"/v1/document-versions/{result.version.id}/rescission",
        json={"note": "not mine to withdraw at all"},
    )

    assert response.status_code == 404
    # "not found", not "forbidden": telling the caller it exists is the disclosure the
    # tier is for. `read_span` makes the same choice deliberately.
    assert response.json()["detail"] == "version not found"
    body = response.text
    assert result.version.source_hash not in body
    assert result.version.object_key not in body


def test_the_entitled_reviewer_can_still_rescind(restricted) -> None:
    """The dual. A route that refuses everyone satisfies the test above."""
    client, result = restricted
    client.app.dependency_overrides[get_identity] = lambda: ADMIN

    response = client.post(
        f"/v1/document-versions/{result.version.id}/rescission",
        json={"note": "withdrawn by the issuing authority"},
    )

    assert response.status_code == 200
    assert response.json()["rescinded_at"] is not None


@pytest.mark.parametrize(
    "axis,document,reader",
    [
        (
            "corpus",
            {"corpus_id": "secret"},
            {"corpora": frozenset({"public"}), "clearance": AccessTier.RESTRICTED},
        ),
        (
            "clearance",
            {"access_tier": AccessTier.RESTRICTED},
            {"corpora": frozenset({"public"}), "clearance": AccessTier.AUTHENTICATED},
        ),
        (
            "classification",
            {"classification": Classification.RESTRICTED, "access_tier": AccessTier.RESTRICTED},
            {"corpora": frozenset({"public"}), "clearance": AccessTier.REVIEWED},
        ),
        (
            "compartment",
            {"compartments": frozenset({"bravo"})},
            {"corpora": frozenset({"public"}), "clearance": AccessTier.RESTRICTED},
        ),
    ],
)
def test_the_near_duplicate_probe_is_not_a_graded_content_oracle(
    tmp_path: Path, axis: str, document: dict, reader: dict
) -> None:
    """A yes/no oracle is a disclosure; a graded one is a reconstruction method.

    `find_near_duplicate` filtered by corpus alone — no clearance, no classification, no
    compartment — and the verdict travels back in the 201 body as the matched version's
    id and a *similarity score*. A curator whose document list is empty could submit a
    guess, read how close it came, and hill-climb toward the text of a restricted order.
    Measured before the fix: exact 1.0, one word changed 0.9375, two words 0.90625.

    One axis at a time, deliberately. The first version of this test put a document
    beyond the reader on all four axes at once, so removing any single predicate left
    the other three refusing and every mutant survived — the second-line-of-defence
    masking that this repository has now been bitten by four times.
    """
    settings = Settings(
        environment="test",
        auth_mode="disabled",
        database_url=f"sqlite:///{tmp_path / f'oracle-{axis}.db'}",
        object_root=str(tmp_path / axis),
        audit_hmac_key="oracle-test-key",
        audit_anchor_path=str(tmp_path / f"{axis}-anchor.json"),
    )
    app = create_app(settings)
    app.dependency_overrides[get_identity] = lambda: ADMIN
    with TestClient(app) as client:
        service = build_ingestion_service(
            client.app.state.repository,
            LocalObjectStore(tmp_path / axis),
            PolicyEngine(),
            ExtractionSettings(False, "ukr"),
        )
        hidden = service.ingest(
            ADMIN,
            DocumentCreate(
                **{
                    "canonical_title": f"Прихований за {axis}",
                    "corpus_id": "public",
                    "issuer": "Генеральний штаб",
                    **document,
                }
            ),
            VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
            "hidden.txt",
            "text/plain",
            RESTRICTED_TEXT.encode("utf-8"),
        )
        probe = Identity(subject="probe", roles=frozenset({"curator"}), **reader)

        # The premise: this reader cannot list the document. Without it the assertion
        # below is about nothing.
        assert client.app.state.repository.list_documents(probe) == []

        # A *near* guess, not the exact bytes: the exact-hash path is its own oracle and
        # has its own test below. One word changed gives similarity 0.90625, over the
        # 0.90 floor, so a probe that was not scoped would name the hidden version.
        guess = service.ingest(
            probe,
            DocumentCreate(
                canonical_title="Здогад",
                corpus_id="public",
                issuer="Здогадувач",
                access_tier=AccessTier.PUBLIC,
            ),
            VersionCreate(revision="1", authority=AuthorityClass.UNKNOWN),
            "guess.txt",
            "text/plain",
            RESTRICTED_TEXT.replace("укриттями", "спорудами").encode("utf-8"),
        )

        assert guess.version.near_duplicate_of_version_id != hidden.version.id
        assert guess.version.near_duplicate_of_version_id is None
        assert guess.version.near_duplicate_similarity is None


def test_the_exact_duplicate_check_does_not_confirm_unreadable_content(tmp_path: Path) -> None:
    """The other half of the same oracle, and the code all but announced it.

    The exact-hash branch was careful not to return the matched *record* to a caller who
    may not see it — and then raised `duplicate source content already exists`, which
    reveals the same fact in prose. A curator who cannot list the document learns that
    these exact bytes are already held, one guess at a time.

    The ingestion is now treated as new: the bytes are stored under the caller's own
    document, the corpus gains a duplicate nobody can see from outside, and the response
    is indistinguishable from any other ingestion.
    """
    settings = Settings(
        environment="test",
        auth_mode="disabled",
        database_url=f"sqlite:///{tmp_path / 'exact.db'}",
        object_root=str(tmp_path / "exact"),
        audit_hmac_key="oracle-test-key",
        audit_anchor_path=str(tmp_path / "exact-anchor.json"),
    )
    app = create_app(settings)
    app.dependency_overrides[get_identity] = lambda: ADMIN
    with TestClient(app) as client:
        service = build_ingestion_service(
            client.app.state.repository,
            LocalObjectStore(tmp_path / "exact"),
            PolicyEngine(),
            ExtractionSettings(False, "ukr"),
        )
        service.ingest(
            ADMIN,
            DocumentCreate(
                canonical_title="Прихований",
                corpus_id="public",
                issuer="Генеральний штаб",
                compartments=frozenset({"bravo"}),
            ),
            VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
            "hidden.txt",
            "text/plain",
            RESTRICTED_TEXT.encode("utf-8"),
        )
        probe = Identity(
            subject="probe",
            roles=frozenset({"curator"}),
            clearance=AccessTier.RESTRICTED,
            corpora=frozenset({"public"}),
        )
        assert client.app.state.repository.list_documents(probe) == []

        # The same bytes, from a caller who cannot see the holder.
        guess = service.ingest(
            probe,
            DocumentCreate(
                canonical_title="Здогад",
                corpus_id="public",
                issuer="Здогадувач",
            ),
            VersionCreate(revision="1", authority=AuthorityClass.UNKNOWN),
            "guess.txt",
            "text/plain",
            RESTRICTED_TEXT.encode("utf-8"),
        )

        assert guess.duplicate is False
        assert guess.extraction_method != "deduplicated"
        assert guess.document.canonical_title == "Здогад"


def test_the_near_duplicate_probe_still_finds_a_duplicate_the_caller_may_see(
    restricted, tmp_path
) -> None:
    """The dual. Scoping the probe to nothing would also pass the test above, and the
    duplicate check exists to stop the same order entering the corpus twice."""
    client, _ = restricted
    service = build_ingestion_service(
        client.app.state.repository,
        LocalObjectStore(tmp_path / "objects"),
        PolicyEngine(),
        ExtractionSettings(False, "ukr"),
    )
    text = "Порядок ведення журналу перевірок затверджується командиром підрозділу.\n"

    first = service.ingest(
        OUTSIDER,
        DocumentCreate(
            canonical_title="Відкритий порядок",
            corpus_id="public",
            issuer="Штаб",
            access_tier=AccessTier.PUBLIC,
        ),
        VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
        "open.txt",
        "text/plain",
        text.encode("utf-8"),
    )
    second = service.ingest(
        OUTSIDER,
        DocumentCreate(
            canonical_title="Той самий порядок, інший запис",
            corpus_id="public",
            issuer="Штаб",
            access_tier=AccessTier.PUBLIC,
        ),
        VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
        "open-again.txt",
        "text/plain",
        # One word changed: simhash similarity 0.90625, just over the 0.90 floor.
        text.replace("командиром", "керівником").encode("utf-8"),
    )

    assert second.version.near_duplicate_of_version_id == first.version.id
    assert second.version.near_duplicate_similarity is not None
