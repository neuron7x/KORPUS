from __future__ import annotations

from datetime import date

from sqlalchemy import insert, select, update

from apps.api.tests.helpers import approve, ingest_text
from korpus.infrastructure.schema import document_compartments, documents, versions

AS_OF = date(2026, 8, 14)


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


def _capture(client, identity):
    return client.app.state.corpus_snapshot_reader.capture(
        identity, frozenset({"public"}), AS_OF
    )


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
