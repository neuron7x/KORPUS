"""Prove caller-owned SQL settings cannot rewrite broker-bound RLS identity.

These are actual PostgreSQL destruction tests, not mock-only policy assertions.
They must run with korpus_app (non-superuser) and a separately authenticated
korpus_authz broker. A successful unauthorized query or write is a hard failure.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.rls_repository import RlsBoundSqlRepository
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import reset_database

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
ADMIN_URL = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL")
AUTHZ_URL = os.getenv("KORPUS_AUTHZ_DATABASE_URL")
REVIEW_URL = os.getenv("KORPUS_REVIEW_DATABASE_URL")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not all((APP_URL, ADMIN_URL, AUTHZ_URL)),
        reason="real app/admin/authz PostgreSQL identities required",
    ),
]

GUC_ATTACKS = (
    ("clearance", "3"),
    ("corpora", "public,restricted-demo"),
    ("classifications", "public,internal,restricted"),
    ("compartments", "need-to-know"),
    ("roles", "user,admin"),
)


def _subject(*, privileged: bool = False) -> Identity:
    return Identity(
        subject="officer" if privileged else "ordinary-reader",
        roles=frozenset({"user", "admin"} if privileged else {"user"}),
        clearance=AccessTier.RESTRICTED if privileged else AccessTier.PUBLIC,
        corpora=frozenset({"public", "restricted-demo"} if privileged else {"public"}),
        compartments=frozenset({"need-to-know"} if privileged else set()),
    )


def _seed(corpus: str, tier: int, classification: str, *, compartments: str = "[]") -> str:
    assert ADMIN_URL is not None
    document_id = str(uuid4())
    admin = create_engine(ADMIN_URL, future=True)
    try:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO documents("
                    "id, canonical_title, corpus_id, issuer, jurisdiction, "
                    "document_type, access_tier, classification, created_at, compartments_json"
                    ") VALUES (:id, :title, :corpus, 'Verifier', 'UA', 'order', "
                    ":tier, :classification, :now, :compartments)"
                ),
                {
                    "id": document_id,
                    "title": "Original authoritative title",
                    "corpus": corpus,
                    "tier": tier,
                    "classification": classification,
                    "now": datetime.now(UTC),
                    "compartments": compartments,
                },
            )
    finally:
        admin.dispose()
    return document_id


def _repository(*, review: bool = False) -> RlsBoundSqlRepository:
    assert APP_URL is not None and AUTHZ_URL is not None
    if review:
        assert REVIEW_URL is not None
    return RlsBoundSqlRepository(
        APP_URL,
        "test-only-audit-key",
        authz_database_url=AUTHZ_URL,
        review_database_url=REVIEW_URL if review else None,
    )


def _visible(connection, document_id: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT count(*) FROM documents WHERE id = :id"), {"id": document_id}
        ).scalar_one()
    )


def _forge_all(connection) -> None:
    for name, value in GUC_ATTACKS:
        connection.execute(
            text("SELECT set_config(:setting, :value, true)"),
            {"setting": f"korpus.{name}", "value": value},
        )


@pytest.mark.parametrize(("axis", "forged"), GUC_ATTACKS)
def test_each_app_owned_session_claim_is_ignored_by_broker(axis: str, forged: str) -> None:
    reset_database()
    public_id = _seed("public", 0, "public")
    restricted_id = _seed("restricted-demo", 3, "restricted")
    repository = _repository()
    try:
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject())
            assert connection.execute(text("SELECT current_user")).scalar_one() == "korpus_app"
            assert _visible(connection, public_id)
            assert not _visible(connection, restricted_id)
            accessor = f"public.korpus_rls_{axis}()"
            before = connection.execute(text(f"SELECT {accessor}")).scalar_one()
            connection.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": f"korpus.{axis}", "value": forged},
            )
            after = connection.execute(text(f"SELECT {accessor}")).scalar_one()
            assert after == before, f"mutable session value replaced broker {axis}"
            assert _visible(connection, public_id)
            assert not _visible(connection, restricted_id)
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject(privileged=True))
            assert _visible(connection, restricted_id), "always-deny is not a security proof"
    finally:
        repository.close()


@pytest.mark.parametrize("operation", ("UPDATE", "DELETE"))
def test_forged_claims_cannot_change_hidden_document(operation: str) -> None:
    reset_database()
    public_id = _seed("public", 0, "public")
    restricted_id = _seed("restricted-demo", 3, "restricted")
    repository = _repository()
    try:
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject())
            assert _visible(connection, public_id)
            assert not _visible(connection, restricted_id)
            _forge_all(connection)
            sql = (
                "UPDATE documents SET canonical_title = 'forged-write' WHERE id = :id"
                if operation == "UPDATE"
                else "DELETE FROM documents WHERE id = :id"
            )
            result = connection.execute(text(sql), {"id": restricted_id})
            assert result.rowcount == 0, f"forged {operation} changed a hidden document"
            visible_result = connection.execute(text(sql), {"id": public_id})
            assert visible_result.rowcount == 0, (
                f"forged {operation} gained writer authority on a visible document"
            )
        assert ADMIN_URL is not None
        admin = create_engine(ADMIN_URL, future=True)
        try:
            with admin.connect() as connection:
                title = connection.execute(
                    text("SELECT canonical_title FROM documents WHERE id = :id"),
                    {"id": restricted_id},
                ).scalar_one()
            assert title == "Original authoritative title"
        finally:
            admin.dispose()
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject(privileged=True))
            authorized = connection.execute(text(sql), {"id": public_id})
            assert authorized.rowcount == 1, f"authorized {operation} was blocked"
    finally:
        repository.close()


def test_forged_claims_cannot_insert_a_restricted_document() -> None:
    reset_database()
    public_id = _seed("public", 0, "public")
    attempt = str(uuid4())
    repository = _repository()
    try:
        with pytest.raises(DBAPIError), repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject())
            assert _visible(connection, public_id)
            _forge_all(connection)
            connection.execute(
                text(
                    "INSERT INTO documents("
                    "id, canonical_title, corpus_id, issuer, jurisdiction, "
                    "document_type, access_tier, classification, created_at, compartments_json"
                    ") VALUES (:id, 'forged-insert', 'restricted-demo', 'Verifier', "
                    "'UA', 'order', 3, 'restricted', :now, '[]')"
                ),
                {"id": attempt, "now": datetime.now(UTC)},
            )
        assert ADMIN_URL is not None
        admin = create_engine(ADMIN_URL, future=True)
        try:
            with admin.connect() as connection:
                assert not _visible(connection, attempt)
        finally:
            admin.dispose()
    finally:
        repository.close()


@pytest.mark.skipif(not REVIEW_URL, reason="real review PostgreSQL role required")
@pytest.mark.parametrize(("axis", "forged"), GUC_ATTACKS)
def test_review_login_cannot_forge_broker_bound_claims(axis: str, forged: str) -> None:
    reset_database()
    public_id = _seed("public", 0, "public")
    restricted_id = _seed("restricted-demo", 3, "restricted")
    repository = _repository(review=True)
    try:
        assert repository.review_engine is not None
        with repository.review_engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject())
            assert connection.execute(text("SELECT current_user")).scalar_one() == "korpus_review"
            assert _visible(connection, public_id)
            assert not _visible(connection, restricted_id)
            accessor = f"public.korpus_rls_{axis}()"
            before = connection.execute(text(f"SELECT {accessor}")).scalar_one()
            connection.execute(
                text("SELECT set_config(:setting, :value, true)"),
                {"setting": f"korpus.{axis}", "value": forged},
            )
            assert connection.execute(text(f"SELECT {accessor}")).scalar_one() == before
            assert _visible(connection, public_id)
            assert not _visible(connection, restricted_id)
        with repository.review_engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject(privileged=True))
            assert _visible(connection, restricted_id), "always-deny is not a review security proof"
    finally:
        repository.close()


@pytest.mark.skipif(not REVIEW_URL, reason="real review PostgreSQL role required")
@pytest.mark.parametrize("operation", ("UPDATE", "DELETE", "INSERT"))
def test_review_login_cannot_mutate_non_review_document_columns(operation: str) -> None:
    reset_database()
    document_id = _seed("public", 0, "public")
    attempted_id = str(uuid4())
    statements = {
        "UPDATE": "UPDATE documents SET canonical_title = 'forged-review' WHERE id = :id",
        "DELETE": "DELETE FROM documents WHERE id = :id",
        "INSERT": (
            "INSERT INTO documents(id, canonical_title, corpus_id, issuer, jurisdiction, "
            "document_type, access_tier, classification, created_at, compartments_json) "
            "VALUES (:id, 'forged-review', 'public', 'Verifier', 'UA', 'order', "
            "0, 'public', :now, '[]')"
        ),
    }
    repository = _repository(review=True)
    try:
        assert repository.review_engine is not None
        with repository.review_engine.connect() as connection:
            transaction = connection.begin()
            try:
                repository._apply_postgres_identity(connection, _subject(privileged=True))
                assert _visible(connection, document_id), (
                    "review identity must retain allowed reads"
                )
                _forge_all(connection)
                target = attempted_id if operation == "INSERT" else document_id
                with pytest.raises(DBAPIError):
                    connection.execute(
                        text(statements[operation]),
                        {"id": target, "now": datetime.now(UTC)},
                    )
            finally:
                transaction.rollback()
        assert ADMIN_URL is not None
        admin = create_engine(ADMIN_URL, future=True)
        try:
            with admin.connect() as connection:
                original = connection.execute(
                    text("SELECT canonical_title FROM documents WHERE id = :id"),
                    {"id": document_id},
                ).scalar_one()
                assert original == "Original authoritative title"
                assert not _visible(connection, attempted_id)
        finally:
            admin.dispose()
    finally:
        repository.close()


@pytest.mark.skipif(not REVIEW_URL, reason="real review PostgreSQL role required")
def test_review_login_cannot_call_the_authorization_broker() -> None:
    assert REVIEW_URL is not None
    review = create_engine(REVIEW_URL, future=True)
    try:
        with review.connect() as connection:
            allowed = connection.execute(
                text("SELECT has_function_privilege(current_user, :fn, 'EXECUTE')"),
                {
                    "fn": "public.korpus_bind_rls_context"
                    "(integer,bigint,name,text,integer,jsonb,jsonb,jsonb,jsonb)"
                },
            ).scalar_one()
            assert allowed is False, "review role has broker EXECUTE privilege"
        with pytest.raises(DBAPIError), review.begin() as connection:
            connection.execute(
                text(
                    "SELECT public.korpus_bind_rls_context(pg_backend_pid(), "
                    "txid_current(), session_user, 'forged-review', 3, "
                    "'[\"public\"]'::jsonb, '[\"public\"]'::jsonb, "
                    "'[]'::jsonb, '[\"admin\"]'::jsonb)"
                )
            )
    finally:
        review.dispose()


@pytest.mark.parametrize("review", (False, True), ids=("app", "review"))
def test_pooled_session_cannot_reuse_a_privileged_binding_or_session_forgery(review: bool) -> None:
    if review and not REVIEW_URL:
        pytest.skip("real review PostgreSQL login required")
    reset_database()
    public_id = _seed("public", 0, "public")
    restricted_id = _seed("restricted-demo", 3, "restricted")
    repository = _repository(review=review)
    try:
        engine = repository.review_engine if review else repository.engine
        assert engine is not None
        with engine.connect() as connection:
            with connection.begin():
                backend_pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
                repository._apply_postgres_identity(connection, _subject(privileged=True))
                assert _visible(connection, restricted_id), "positive broker binding failed"
            with connection.begin():
                assert (
                    connection.execute(text("SELECT pg_backend_pid()")).scalar_one() == backend_pid
                )
                assert not _visible(connection, restricted_id), (
                    "previous transaction's broker identity leaked"
                )
            with connection.begin():
                repository._apply_postgres_identity(connection, _subject())
                assert _visible(connection, public_id)
                assert not _visible(connection, restricted_id)
                for axis, forged in GUC_ATTACKS:
                    connection.execute(
                        text("SELECT set_config(:setting, :value, false)"),
                        {"setting": f"korpus.{axis}", "value": forged},
                    )
                assert not _visible(connection, restricted_id), (
                    "persistent GUC replaced broker identity"
                )
            with connection.begin():
                assert not _visible(connection, restricted_id), (
                    "unbound transaction trusted forged session GUC"
                )
            with connection.begin():
                repository._apply_postgres_identity(connection, _subject())
                assert _visible(connection, public_id)
                assert not _visible(connection, restricted_id), (
                    "forged GUC survived trusted rebinding"
                )
    finally:
        repository.close()


@pytest.mark.parametrize(
    ("axis", "tier", "corpus", "classification", "compartments"),
    [
        ("clearance", 3, "public", "public", "[]"),
        ("corpora", 0, "restricted-demo", "public", "[]"),
        ("classifications", 0, "public", "restricted", "[]"),
        ("compartments", 0, "public", "public", '["need-to-know"]'),
    ],
)
@pytest.mark.parametrize("review", (False, True), ids=("app", "review"))
def test_claim_axis_isolation_rejects_forged_settings(
    axis: str,
    tier: int,
    corpus: str,
    classification: str,
    compartments: str,
    review: bool,
) -> None:
    if review and not REVIEW_URL:
        pytest.skip("real review PostgreSQL role required")
    reset_database()
    public_id = _seed("public", 0, "public")
    restricted_id = _seed(corpus, tier, classification, compartments=compartments)
    repository = _repository(review=review)
    try:
        engine = repository.review_engine if review else repository.engine
        assert engine is not None
        with engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject())
            assert _visible(connection, public_id), "unrestricted positive control failed"
            assert not _visible(connection, restricted_id), "axis isolation baseline failed"
            connection.execute(
                text("SELECT set_config(:setting, :value, true)"),
                {"setting": f"korpus.{axis}", "value": dict(GUC_ATTACKS)[axis]},
            )
            assert _visible(connection, public_id)
            assert not _visible(connection, restricted_id), (
                f"forged {axis} bypassed isolated document restriction"
            )
        with engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject(privileged=True))
            assert _visible(connection, restricted_id), (
                f"the legitimate {axis} grant does not enable visibility"
            )
    finally:
        repository.close()


@pytest.mark.parametrize("table", ("documents", "document_versions"))
def test_broker_admin_cannot_cascade_delete_sealed_evidence(tmp_path: Path, table: str) -> None:
    """An app-admin DELETE must not erase reviewer-sealed evidence via an FK cascade."""
    from korpus.domain.models import (
        AuthorityClass,
        Classification,
        DocumentRecord,
        DocumentVersionRecord,
        EvidenceSpanRecord,
        ReviewState,
    )
    from korpus.infrastructure.repository import SqlRepository

    reset_database()
    assert ADMIN_URL is not None
    ids: dict[str, tuple[str, str, str]] = {}
    owner = SqlRepository(
        ADMIN_URL, "test-only-audit-key", audit_anchor_path=tmp_path / "owner-anchor.json"
    )
    try:
        for label, sealed in (("sealed", True), ("draft", False)):
            document = DocumentRecord(
                canonical_title=f"{label} parent deletion control",
                corpus_id="public",
                issuer="Verifier",
                jurisdiction="UA",
                document_type="order",
                access_tier=AccessTier.PUBLIC,
                classification=Classification.PUBLIC,
            )
            version = DocumentVersionRecord(
                document_id=document.id,
                revision="1",
                source_hash=("a" if sealed else "b") * 64,
                object_key=f"deletion-control/{label}",
                mime_type="text/plain",
                authority=AuthorityClass.OFFICIAL_UA,
                review_state=ReviewState.APPROVED if sealed else ReviewState.QUARANTINED,
                publication_date=date(2020, 1, 1),
                is_current=sealed,
            )
            span = EvidenceSpanRecord(
                version_id=version.id, ordinal=0, text=f"{label} evidence for FK integrity"
            )
            owner.create_document_bundle(
                _subject(privileged=True), document, version, [span], {"fixture": label}
            )
            ids[label] = (str(document.id), str(version.id), str(span.id))
    finally:
        owner.close()

    target = 0 if table == "documents" else 1
    repository = _repository()
    try:
        with repository.engine.connect() as connection:
            transaction = connection.begin()
            try:
                repository._apply_postgres_identity(connection, _subject(privileged=True))
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM evidence_spans WHERE id = :id"),
                        {"id": ids["sealed"][2]},
                    ).scalar_one()
                    == 1
                )
                sealed = connection.execute(
                    text(
                        "SELECT review_state, evidence_digest FROM document_versions WHERE id = :id"
                    ),
                    {"id": ids["sealed"][1]},
                ).one()
                assert sealed[0] == "approved" and sealed[1], "fixture has no approved seal"
                control = connection.execute(
                    text(f"DELETE FROM {table} WHERE id = :id"),
                    {"id": ids["draft"][target]},
                )
                assert control.rowcount == 1, "admin DELETE positive control failed"
                try:
                    with connection.begin_nested():
                        attempt = connection.execute(
                            text(f"DELETE FROM {table} WHERE id = :id"),
                            {"id": ids["sealed"][target]},
                        )
                        parent_count = connection.execute(
                            text(f"SELECT count(*) FROM {table} WHERE id = :id"),
                            {"id": ids["sealed"][target]},
                        ).scalar_one()
                        evidence_count = connection.execute(
                            text("SELECT count(*) FROM evidence_spans WHERE id = :id"),
                            {"id": ids["sealed"][2]},
                        ).scalar_one()
                        assert (attempt.rowcount, parent_count, evidence_count) == (0, 1, 1), (
                            f"sealed {table} deletion accepted: deleted={attempt.rowcount}, "
                            f"parent_survivors={parent_count}, evidence_survivors={evidence_count}"
                        )
                except DBAPIError:
                    # Rejected by a database authorization/immutability guard.
                    pass
            finally:
                transaction.rollback()
    finally:
        repository.close()


@pytest.mark.parametrize(
    "field",
    ("document_id", "revision", "source_hash", "object_key", "authority", "source_uri"),
)
def test_broker_admin_cannot_rewrite_approved_version_provenance(
    tmp_path: Path, field: str
) -> None:
    """Reviewer-sealed source identity must survive direct app SQL, not only API calls."""
    from korpus.domain.models import (
        AuthorityClass,
        Classification,
        DocumentRecord,
        DocumentVersionRecord,
        EvidenceSpanRecord,
        ReviewState,
    )
    from korpus.infrastructure.repository import SqlRepository

    reset_database()
    assert ADMIN_URL is not None
    carrier_id = _seed("public", 0, "public")
    owner = SqlRepository(
        ADMIN_URL, "test-only-audit-key", audit_anchor_path=tmp_path / "provenance-anchor.json"
    )
    versions: dict[str, str] = {}
    try:
        for label, state in (
            ("approved", ReviewState.APPROVED),
            ("draft", ReviewState.QUARANTINED),
        ):
            doc = DocumentRecord(
                canonical_title=f"{label} provenance DML control",
                corpus_id="public",
                issuer="Verifier",
                jurisdiction="UA",
                document_type="order",
                access_tier=AccessTier.PUBLIC,
                classification=Classification.PUBLIC,
            )
            version = DocumentVersionRecord(
                document_id=doc.id,
                revision="1",
                source_hash=("a" if label == "approved" else "b") * 64,
                object_key=f"provenance/{label}",
                mime_type="text/plain",
                authority=AuthorityClass.OFFICIAL_UA,
                review_state=state,
                publication_date=date(2020, 1, 1),
                is_current=label == "approved",
            )
            span = EvidenceSpanRecord(version_id=version.id, ordinal=0, text=f"{label} span")
            owner.create_document_bundle(
                _subject(privileged=True), doc, version, [span], {"fixture": label}
            )
            versions[label] = str(version.id)
    finally:
        owner.close()

    new_values = {
        "document_id": carrier_id,
        "revision": "unreviewed-revision",
        "source_hash": "c" * 64,
        "object_key": "unreviewed/object",
        "authority": "adversary",
        "source_uri": "https://unreviewed.invalid/source",
    }
    repository = _repository()
    try:
        with repository.engine.connect() as connection:
            transaction = connection.begin()
            try:
                repository._apply_postgres_identity(connection, _subject(privileged=True))
                assert connection.execute(text("SELECT current_user")).scalar_one() == "korpus_app"
                for label in ("approved", "draft"):
                    version_id = versions[label]
                    original = connection.execute(
                        text(f"SELECT {field} FROM document_versions WHERE id = :id"),
                        {"id": version_id},
                    ).scalar_one()
                    assert original != new_values[field], "mutation fixture must differ"
                    changed = False
                    try:
                        with connection.begin_nested() as savepoint:
                            result = connection.execute(
                                text(
                                    f"UPDATE document_versions SET {field} = :value WHERE id = :id"
                                ),
                                {"value": new_values[field], "id": version_id},
                            )
                            observed = connection.execute(
                                text(f"SELECT {field} FROM document_versions WHERE id = :id"),
                                {"id": version_id},
                            ).scalar_one()
                            changed = result.rowcount == 1 and observed == new_values[field]
                            savepoint.rollback()
                    except DBAPIError:
                        if label == "draft":
                            raise
                    assert changed is (label == "draft"), (
                        f"{label} {field}: approved provenance was writable or draft was blocked"
                    )
            finally:
                transaction.rollback()
    finally:
        repository.close()
