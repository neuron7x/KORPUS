from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import insert, select, update

from apps.api.tests.helpers import approve, ingest_text, ingest_version
from korpus.infrastructure.schema import document_compartments, documents, versions

AS_OF = date(2026, 8, 14)
PUBLIC = frozenset({"public"})


def _approved(client) -> tuple[str, str]:
    payload = ingest_text(
        client,
        title="Semantic release baseline",
        text="Журнал контрольних перевірок ведеться щодоби відповідальною особою.",
    )
    document_id = str(payload["document"]["id"])
    version_id = str(payload["version"]["id"])
    approve(client, version_id)
    return document_id, version_id


def _capture(client, identity, corpora=PUBLIC):
    return client.app.state.corpus_snapshot_reader.capture(identity, corpora, AS_OF)


def _mutate_and_require_new_release(
    repository,
    identity,
    statement,
    before,
    client,
    corpora,
):
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, identity)
        connection.execute(statement)
    after = _capture(client, identity, corpora)
    assert after.state_epoch > before.state_epoch
    assert after.release_id != before.release_id
    return after


def test_answer_visible_title_change_changes_release_without_changing_evidence(
    client, admin_identity
) -> None:
    document_id, version_id = _approved(client)
    repository = client.app.state.repository
    before = _capture(client, admin_identity)
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, admin_identity)
        source_hash, evidence_digest = connection.execute(
            select(versions.c.source_hash, versions.c.evidence_digest).where(
                versions.c.id == version_id
            )
        ).one()
        connection.execute(
            update(documents)
            .where(documents.c.id == document_id)
            .values(canonical_title="Semantic release changed title")
        )
    after = _capture(client, admin_identity)
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, admin_identity)
        stable = connection.execute(
            select(versions.c.source_hash, versions.c.evidence_digest).where(
                versions.c.id == version_id
            )
        ).one()

    assert tuple(stable) == (source_hash, evidence_digest)
    assert after.release_id != before.release_id


def test_ranking_authority_change_changes_release_without_changing_evidence(
    client, admin_identity
) -> None:
    _document_id, version_id = _approved(client)
    repository = client.app.state.repository
    before = _capture(client, admin_identity)
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, admin_identity)
        evidence_digest = connection.execute(
            select(versions.c.evidence_digest).where(versions.c.id == version_id)
        ).scalar_one()
        connection.execute(
            update(versions)
            .where(versions.c.id == version_id)
            .values(authority="official_allied")
        )
    after = _capture(client, admin_identity)
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, admin_identity)
        stable_digest = connection.execute(
            select(versions.c.evidence_digest).where(versions.c.id == version_id)
        ).scalar_one()

    assert stable_digest == evidence_digest
    assert after.release_id != before.release_id


def test_visibility_compartment_change_changes_release_while_member_remains_visible(
    client, admin_identity
) -> None:
    document_id, _version_id = _approved(client)
    repository = client.app.state.repository
    identity = admin_identity.model_copy(update={"compartments": frozenset({"alpha"})})
    before = _capture(client, identity)
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, identity)
        connection.execute(
            insert(document_compartments).values(
                document_id=document_id,
                compartment="alpha",
            )
        )
    after = _capture(client, identity)

    assert before.release_id != after.release_id


def test_each_stable_semantic_projection_field_changes_release(
    client, admin_identity
) -> None:
    document_id, version_id = _approved(client)
    shadow = ingest_version(
        client,
        document_id,
        revision="shadow",
        text="Окремий неухвалений контрольний варіант для зовнішнього ключа.",
    )
    shadow_version_id = str(shadow["version"]["id"])
    repository = client.app.state.repository
    identity = admin_identity.model_copy(update={"compartments": frozenset({"alpha"})})
    corpora = frozenset({"public", "training"})
    current = _capture(client, identity, corpora)

    statements = (
        update(documents)
        .where(documents.c.id == document_id)
        .values(canonical_title="Title v2"),
        update(documents).where(documents.c.id == document_id).values(corpus_id="training"),
        update(documents).where(documents.c.id == document_id).values(access_tier=1),
        update(documents)
        .where(documents.c.id == document_id)
        .values(classification="internal"),
        update(documents)
        .where(documents.c.id == document_id)
        .values(compartments_json='["alpha"]'),
        insert(document_compartments).values(
            document_id=document_id,
            compartment="alpha",
        ),
        update(versions).where(versions.c.id == version_id).values(revision="2.0"),
        update(versions)
        .where(versions.c.id == version_id)
        .values(source_uri="https://source.invalid/release-v2"),
        update(versions)
        .where(versions.c.id == version_id)
        .values(publication_date=date(2021, 1, 1)),
        update(versions)
        .where(versions.c.id == version_id)
        .values(effective_from=date(2022, 1, 1)),
        update(versions)
        .where(versions.c.id == version_id)
        .values(effective_until=date(2030, 1, 1)),
        update(versions)
        .where(versions.c.id == version_id)
        .values(rescinded_at=datetime(2030, 1, 1, tzinfo=UTC)),
        update(versions)
        .where(versions.c.id == version_id)
        .values(authority="official_allied"),
        update(versions)
        .where(versions.c.id == version_id)
        .values(supersedes_version_id=shadow_version_id),
    )
    for statement in statements:
        current = _mutate_and_require_new_release(
            repository, identity, statement, current, client, corpora
        )


def test_irrelevant_issuer_change_advances_epoch_but_not_semantic_release(
    client, admin_identity
) -> None:
    document_id, _version_id = _approved(client)
    repository = client.app.state.repository
    before = _capture(client, admin_identity)
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, admin_identity)
        connection.execute(
            update(documents)
            .where(documents.c.id == document_id)
            .values(issuer="Changed non-answer issuer metadata")
        )
    after = _capture(client, admin_identity)

    assert after.state_epoch > before.state_epoch
    assert after.release_id == before.release_id
