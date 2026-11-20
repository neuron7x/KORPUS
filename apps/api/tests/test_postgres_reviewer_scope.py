"""Native reviewer-only policy positives and independent database denial controls."""

from __future__ import annotations

import json

import pytest
from korpus.domain.models import AccessTier, Classification, ReviewState
from korpus.infrastructure.repository import NonRetryableWriteError
from korpus.infrastructure.schema import documents, versions
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from apps.api.tests.review_postgres_support import (
    APPROVER,
    CONTENT,
    METADATA,
    ReviewPostgres,
    actor,
)
from apps.api.tests.review_postgres_support import (
    review_postgres as review_postgres,
)

pytestmark = pytest.mark.postgres


def test_rls_hidden_tier_update_aborts_the_review_transaction(review_postgres) -> None:
    store = review_postgres
    document, version = store.seed()
    store.transition(METADATA, version.id, ReviewState.METADATA_REVIEWED)
    store.transition(CONTENT, version.id, ReviewState.CONTENT_REVIEWED)
    before = store.repository.verify_audit().event_count
    user = actor("not-a-reviewer", "user")
    with pytest.raises(NonRetryableWriteError, match="optimistic document tier update failed"):
        store.repository.transition_version(
            user,
            version.id,
            ReviewState.CONTENT_REVIEWED,
            ReviewState.APPROVED,
            "raw repository denial control",
            access_tier=AccessTier.PUBLIC,
        )
    assert (
        store.repository.get_version(CONTENT, version.id).review_state
        is ReviewState.CONTENT_REVIEWED
    )
    assert store.repository.get_document(CONTENT, document.id).access_tier is AccessTier.PUBLIC
    assert store.repository.verify_audit().event_count == before


@pytest.mark.parametrize("review_postgres", ["configured", "custom"], indirect=True)
@pytest.mark.parametrize("tier", [AccessTier.PUBLIC, AccessTier.AUTHENTICATED])
def test_reviewer_only_content_and_approval_use_review_capability(
    review_postgres: ReviewPostgres, tier
) -> None:
    store = review_postgres
    document, version = store.seed()
    metadata = store.transition(METADATA, version.id, ReviewState.METADATA_REVIEWED)
    content = store.transition(CONTENT, version.id, ReviewState.CONTENT_REVIEWED)
    approved = store.transition(APPROVER, version.id, ReviewState.APPROVED, access_tier=tier)
    assert [metadata.state_version, content.state_version, approved.state_version] == [1, 2, 3]
    assert approved.is_current and approved.approved_by == APPROVER.subject
    assert approved.metadata_reviewed_by == METADATA.subject
    assert approved.content_reviewed_by == CONTENT.subject
    assert CONTENT.roles == APPROVER.roles == frozenset({"reviewer"})
    assert store.repository.get_document(APPROVER, document.id).access_tier is tier
    assert store.repository.verify_audit().valid


def test_application_login_cannot_borrow_review_policy(review_postgres) -> None:
    repository = review_postgres.repository
    document, version = review_postgres.seed()
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, CONTENT)
        assert (
            connection.execute(
                update(versions).where(versions.c.id == str(version.id)).values(revision="forged")
            ).rowcount
            == 0
        )
    for statement in (
        update(versions)
        .where(versions.c.id == str(version.id))
        .values(review_state="metadata_reviewed"),
        update(documents).where(documents.c.id == str(document.id)).values(access_tier=1),
    ):
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, CONTENT)
            with pytest.raises(DBAPIError) as denied:
                connection.execute(statement)
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"
            connection.rollback()
    assert repository.get_version(CONTENT, version.id).revision == "1"


@pytest.mark.parametrize("bound", [False, True])
def test_review_login_needs_trusted_role_after_pool_reuse(review_postgres, bound) -> None:
    repository = review_postgres.repository
    _, version = review_postgres.seed()
    with repository.review_engine.begin() as connection:
        repository._apply_postgres_identity(connection, CONTENT)
        assert connection.execute(select(versions.c.id)).scalar_one() == str(version.id)
        backend = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
    with repository.review_engine.begin() as connection:
        assert connection.execute(text("SELECT pg_backend_pid()")).scalar_one() == backend
        if bound:
            repository._apply_postgres_identity(connection, actor("ordinary-reader", "user"))
        connection.execute(
            text("SELECT set_config('korpus.roles', 'reviewer,curator,admin', true)")
        )
        result = connection.execute(
            update(versions).where(versions.c.id == str(version.id)).values(revision="forged")
        )
        assert result.rowcount == 0


@pytest.mark.parametrize("axis", ["corpus", "tier", "classification", "compartment"])
def test_original_visibility_axes_still_hide_both_update_targets(review_postgres, axis) -> None:
    repository = review_postgres.repository
    options = {
        "corpus": {"corpus_id": "hidden"},
        "tier": {"access_tier": AccessTier.RESTRICTED},
        "classification": {
            "classification": Classification.INTERNAL,
            "access_tier": AccessTier.AUTHENTICATED,
        },
        "compartment": {"compartments": frozenset({"archive"})},
    }[axis]
    document, version = review_postgres.seed(**options)
    identity = actor(
        "scoped-reviewer",
        "reviewer",
        clearance=AccessTier.PUBLIC if axis == "tier" else AccessTier.RESTRICTED,
        compartments=frozenset() if axis == "compartment" else frozenset({"archive"}),
    )
    with repository.review_engine.begin() as connection:
        repository._apply_postgres_identity(connection, identity)
        if axis == "classification":
            target = connection.execute(
                text("SELECT pg_backend_pid(), txid_current(), session_user")
            ).one()
            # Keep tier/corpus/compartments sufficient; constrain only the broker's class set.
            with repository.authz_engine.begin() as broker:
                broker.execute(
                    text(
                        "SELECT public.korpus_bind_rls_context(:pid, :xid, CAST(:login AS name), :subject, :clearance, "
                        "CAST(:corpora AS jsonb), CAST(:classes AS jsonb), CAST(:compartments AS jsonb), CAST(:roles AS jsonb))"
                    ),
                    dict(
                        pid=target[0],
                        xid=target[1],
                        login=target[2],
                        subject=identity.subject,
                        clearance=int(identity.clearance),
                        corpora=json.dumps(sorted(identity.corpora)),
                        classes='["public"]',
                        compartments=json.dumps(sorted(identity.compartments)),
                        roles='["reviewer"]',
                    ),
                )
        assert (
            connection.execute(
                update(versions).where(versions.c.id == str(version.id)).values(revision="hidden")
            ).rowcount
            == 0
        )
        assert (
            connection.execute(
                update(documents)
                .where(documents.c.id == str(document.id))
                .values(access_tier=int(document.access_tier))
            ).rowcount
            == 0
        )


@pytest.mark.parametrize("target", ["version_parent", "document_tier"])
def test_with_check_prevents_new_row_scope_escape(review_postgres, target) -> None:
    repository = review_postgres.repository
    document, version = review_postgres.seed()
    hidden, _ = review_postgres.seed(corpus_id="hidden")
    limited = actor("public-reviewer", "reviewer", clearance=AccessTier.PUBLIC)
    statement = (
        update(versions).where(versions.c.id == str(version.id)).values(document_id=str(hidden.id))
        if target == "version_parent"
        else update(documents).where(documents.c.id == str(document.id)).values(access_tier=1)
    )
    with repository.review_engine.begin() as connection:
        repository._apply_postgres_identity(connection, limited)
        assert connection.execute(
            select(versions.c.id).where(versions.c.id == str(version.id))
        ).scalar_one()
        with pytest.raises(DBAPIError) as denied:
            connection.execute(statement)
        assert getattr(denied.value.orig, "sqlstate", None) == "42501"
        connection.rollback()


def test_review_capability_keeps_column_and_sealed_provenance_denials(review_postgres) -> None:
    store = review_postgres
    document, version = store.seed()
    store.transition(METADATA, version.id, ReviewState.METADATA_REVIEWED)
    store.transition(CONTENT, version.id, ReviewState.CONTENT_REVIEWED)
    store.transition(APPROVER, version.id, ReviewState.APPROVED)
    for statement, sqlstate in (
        (
            update(documents)
            .where(documents.c.id == str(document.id))
            .values(canonical_title="forged"),
            "42501",
        ),
        (
            update(versions)
            .where(versions.c.id == str(version.id))
            .values(source_uri="https://invalid.example/forged"),
            "23514",
        ),
    ):
        with store.repository.review_engine.begin() as connection:
            store.repository._apply_postgres_identity(connection, APPROVER)
            with pytest.raises(DBAPIError) as denied:
                connection.execute(statement)
            assert getattr(denied.value.orig, "sqlstate", None) == sqlstate
            connection.rollback()
