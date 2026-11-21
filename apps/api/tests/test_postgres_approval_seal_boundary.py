"""Execute approval/seal destruction attempts as the real app and review logins."""

from __future__ import annotations

import json

import pytest
from korpus.application.corpus_snapshot import version_evidence_digest
from korpus.domain.models import ReviewState
from korpus.infrastructure.schema import SCHEMA_REVISION, audits, spans, versions
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from apps.api.tests.review_postgres_support import APPROVER, CONTENT, CURATOR, METADATA
from apps.api.tests.review_postgres_support import (
    review_postgres as review_postgres,
)

pytestmark = pytest.mark.postgres
FORGED_DIGEST = "f" * 64


def _record_runtime(connection, request) -> None:
    """Attach the physical identity and migrated revision to each native JUnit node."""
    role = connection.execute(
        text(
            "SELECT current_user AS runtime_role, session_user AS login, "
            "r.rolsuper, r.rolbypassrls, "
            "pg_has_role(current_user, c.relowner, 'MEMBER') AS owner_member, "
            "current_setting('server_version_num')::integer AS server_version "
            "FROM pg_roles r, pg_class c "
            "WHERE r.rolname = current_user AND c.oid = 'public.document_versions'::regclass"
        )
    ).one()
    assert role.runtime_role == role.login == connection.engine.url.username
    assert role.rolsuper is False and role.rolbypassrls is False
    assert role.owner_member is False
    assert role.server_version // 10000 == 17
    revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == SCHEMA_REVISION
    request.node.user_properties.extend(
        (
            ("postgres_server_version_num", role.server_version),
            ("database_role", role.runtime_role),
            ("session_user", role.login),
            ("runtime_is_superuser", role.rolsuper),
            ("runtime_bypasses_rls", role.rolbypassrls),
            ("runtime_is_table_owner_member", role.owner_member),
            ("migration_revision", revision),
        )
    )


def _snapshot(store, version_id):
    """Read persisted rows through an entitled application identity, never the owner."""
    with store.repository.engine.begin() as connection:
        store.repository._apply_postgres_identity(connection, CURATOR)
        version = dict(
            connection.execute(select(versions).where(versions.c.id == str(version_id)))
            .mappings()
            .one()
        )
        evidence = [
            dict(row)
            for row in connection.execute(
                select(spans)
                .where(spans.c.version_id == str(version_id))
                .order_by(spans.c.ordinal, spans.c.id)
            ).mappings()
        ]
        audit = [
            dict(row)
            for row in connection.execute(select(audits).order_by(audits.c.sequence)).mappings()
        ]
    assert evidence
    return {"version": version, "evidence": evidence, "audit": audit}


def _approve_with_exact_seal(store, version_id):
    """Positive control: separated reviewers seal persisted spans and append an audit."""
    before = _snapshot(store, version_id)
    for identity, state in (
        (METADATA, ReviewState.METADATA_REVIEWED),
        (CONTENT, ReviewState.CONTENT_REVIEWED),
        (APPROVER, ReviewState.APPROVED),
    ):
        assert store.transition(identity, version_id, state).review_state is state
    sealed = _snapshot(store, version_id)
    expected = version_evidence_digest(
        (row["id"], row["ordinal"], row["page"], row["section"], row["text"], row["text_hash"])
        for row in sealed["evidence"]
    )
    assert sealed["version"]["evidence_digest"] == expected != FORGED_DIGEST
    assert sealed["version"]["is_current"] is True
    assert sealed["version"]["approved_by"] == APPROVER.subject
    assert sealed["version"]["metadata_reviewed_by"] == METADATA.subject
    assert sealed["version"]["content_reviewed_by"] == CONTENT.subject
    assert sealed["version"]["state_version"] == before["version"]["state_version"] + 3
    assert sealed["evidence"] == before["evidence"]
    assert len(sealed["audit"]) == len(before["audit"]) + 3
    event = sealed["audit"][-1]
    assert event["action"] == "document.review_transition"
    assert event["resource_id"] == str(version_id)
    assert event["actor_subject"] == APPROVER.subject
    assert json.loads(event["payload_json"])["evidence_digest"] == expected
    assert store.repository.verify_audit().valid
    return sealed


def _attempt_and_rollback(store, version_id, login_kind, changes, request) -> None:
    """A preceding permitted write proves both target reachability and full rollback."""
    repository = store.repository
    engine, identity = (
        (repository.engine, CURATOR)
        if login_kind == "app"
        else (repository.review_engine, APPROVER)
    )
    assert engine is not None
    before = _snapshot(store, version_id)
    target = versions.c.id == str(version_id)
    with engine.begin() as connection:
        repository._apply_postgres_identity(connection, identity)
        _record_runtime(connection, request)
        assert connection.execute(select(versions.c.id).where(target)).scalar_one() == str(
            version_id
        )
        assert (
            connection.execute(
                update(versions).where(target).values(state_version=versions.c.state_version + 1)
            ).rowcount
            == 1
        )
        if login_kind == "review":
            # The review login can write the seal column; only a changed seal must fail.
            assert (
                connection.execute(
                    update(versions)
                    .where(target)
                    .values(evidence_digest=before["version"]["evidence_digest"])
                ).rowcount
                == 1
            )
        with pytest.raises(DBAPIError) as denied:
            connection.execute(update(versions).where(target).values(**changes))
        sqlstate = getattr(denied.value.orig, "sqlstate", None)
        assert sqlstate == ("42501" if login_kind == "app" else "P0001")
        if login_kind == "review":
            assert "sealed evidence digest is immutable" in str(denied.value.orig)
        connection.rollback()
    after = _snapshot(store, version_id)
    assert after == before
    assert store.repository.verify_audit().valid
    request.node.user_properties.extend(
        (
            ("bound_subject", identity.subject),
            ("bound_roles", ",".join(sorted(identity.roles))),
            ("denial_sqlstate", sqlstate),
            ("visible_target_rows", 1),
            ("permitted_write_rows", 1),
            ("review_state_before", before["version"]["review_state"]),
            ("review_state_after", after["version"]["review_state"]),
            ("state_version_before", before["version"]["state_version"]),
            ("state_version_after", after["version"]["state_version"]),
            ("evidence_digest_before", before["version"]["evidence_digest"]),
            ("evidence_digest_after", after["version"]["evidence_digest"]),
            ("attempted_evidence_digest", changes["evidence_digest"]),
            ("evidence_rows_before", len(before["evidence"])),
            ("evidence_rows_after", len(after["evidence"])),
            ("audit_events_before", len(before["audit"])),
            ("audit_events_after", len(after["audit"])),
            ("transaction_rollback_preserved_snapshot", after == before),
        )
    )


def test_app_update_cannot_forge_approval_and_evidence_seal(review_postgres, request) -> None:
    store = review_postgres
    _, version = store.seed()
    _attempt_and_rollback(
        store,
        version.id,
        "app",
        {"review_state": ReviewState.APPROVED.value, "evidence_digest": FORGED_DIGEST},
        request,
    )
    # A denied forgery must leave the same version able to complete legitimate review.
    _approve_with_exact_seal(store, version.id)


@pytest.mark.parametrize("login_kind", ["app", "review"])
@pytest.mark.parametrize(
    "lifecycle", [ReviewState.APPROVED, ReviewState.REJECTED], ids=["approved", "rejected"]
)
@pytest.mark.parametrize("replacement", [FORGED_DIGEST, None], ids=["changed", "null"])
def test_runtime_logins_cannot_change_or_clear_seal_after_approval(
    review_postgres, request, login_kind, lifecycle, replacement
) -> None:
    store = review_postgres
    _, version = store.seed()
    sealed = _approve_with_exact_seal(store, version.id)
    if lifecycle is ReviewState.REJECTED:
        assert (
            store.transition(APPROVER, version.id, ReviewState.REJECTED).review_state
            is ReviewState.REJECTED
        )
        rejected = _snapshot(store, version.id)
        assert rejected["version"]["evidence_digest"] == sealed["version"]["evidence_digest"]
        assert rejected["version"]["is_current"] is False
        assert len(rejected["audit"]) == len(sealed["audit"]) + 1
    _attempt_and_rollback(store, version.id, login_kind, {"evidence_digest": replacement}, request)
