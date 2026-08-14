from __future__ import annotations

import json
import os
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import POSTGRES_ADMIN_URL, reset_database
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.rls_identity import RlsIdentityBinder

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL") or os.getenv("KORPUS_TEST_DATABASE_URL")
REVIEW_URL = os.getenv("KORPUS_REVIEW_DATABASE_URL")
IDENTITY_URL = os.getenv("RLS_IDENTITY_DATABASE_URL")
pytestmark = pytest.mark.postgres

LOW = Identity(
    subject="rls-low",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public-corpus"}),
    compartments=frozenset(),
)


def _require_boundary() -> None:
    if not APP_URL or not POSTGRES_ADMIN_URL or not REVIEW_URL or not IDENTITY_URL:
        pytest.skip("split PostgreSQL app/review/identity URLs are required")


def _engine(url: str):
    return create_engine(url, future=True, pool_pre_ping=True)


def _binder(primary_url: str, peer_url: str) -> RlsIdentityBinder:
    assert IDENTITY_URL
    return RlsIdentityBinder(
        primary_url,
        IDENTITY_URL,
        {"future": True, "pool_pre_ping": True},
        review_database_url=peer_url,
    )


def _seed_document(
    document_id: str,
    *,
    corpus: str = "public-corpus",
    access_tier: int = 0,
    classification: str = "public",
    compartments: tuple[str, ...] = (),
) -> None:
    assert POSTGRES_ADMIN_URL
    admin = _engine(POSTGRES_ADMIN_URL)
    try:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO documents("
                    "id,canonical_title,corpus_id,issuer,jurisdiction,document_type,"
                    "access_tier,classification,compartments_json,created_at"
                    ") VALUES ("
                    ":id,'protected',:corpus,'issuer','UA','reference',"
                    ":tier,:classification,:compartments,statement_timestamp())"
                ),
                {
                    "id": document_id,
                    "corpus": corpus,
                    "tier": access_tier,
                    "classification": classification,
                    "compartments": json.dumps(list(compartments), separators=(",", ":")),
                },
            )
    finally:
        admin.dispose()


def _secure_claims(connection) -> tuple[object, ...]:
    return tuple(
        connection.execute(
            text(
                "SELECT public.korpus_rls_clearance(), public.korpus_rls_corpora(), "
                "public.korpus_rls_classifications(), public.korpus_rls_compartments(), "
                "public.korpus_rls_roles()"
            )
        ).one()
    )


def _visible(connection, document_id: str) -> int:
    return int(
        connection.execute(
            text("SELECT count(*) FROM documents WHERE id=:id"),
            {"id": document_id},
        ).scalar_one()
    )


def _target_identity(connection) -> tuple[int, object, str, str]:
    row = connection.execute(
        text(
            "SELECT pg_catalog.pg_backend_pid(), a.backend_start, "
            "pg_catalog.pg_current_xact_id()::text, session_user "
            "FROM pg_catalog.pg_stat_activity a "
            "WHERE a.pid=pg_catalog.pg_backend_pid()"
        )
    ).one()
    return int(row[0]), row[1], str(row[2]), str(row[3])


def test_app_credential_cannot_write_or_assume_identity_boundary() -> None:
    _require_boundary()
    reset_database()
    assert APP_URL
    app = _engine(APP_URL)
    try:
        with pytest.raises(DBAPIError), app.begin() as connection:
            connection.execute(text("SELECT * FROM public.korpus_rls_identity_bindings"))
        with pytest.raises(DBAPIError), app.begin() as connection:
            connection.execute(text("SET ROLE korpus_identity_runtime"))
        with pytest.raises(DBAPIError), app.begin() as connection:
            connection.execute(
                text(
                    "SELECT public.korpus_bind_rls_identity("
                    "pg_catalog.pg_backend_pid(), "
                    "(SELECT backend_start FROM pg_catalog.pg_stat_activity "
                    " WHERE pid=pg_catalog.pg_backend_pid()), "
                    "pg_catalog.pg_current_xact_id()::text, session_user, "
                    "'forged', 3, 'secret-corpus', 'public,internal,restricted', "
                    "'omega', 'admin,curator')"
                )
            )
    finally:
        app.dispose()


def test_identity_broker_cannot_read_binding_table_directly() -> None:
    _require_boundary()
    reset_database()
    assert IDENTITY_URL
    broker = _engine(IDENTITY_URL)
    try:
        with pytest.raises(DBAPIError), broker.begin() as connection:
            connection.execute(text("SELECT * FROM public.korpus_rls_identity_bindings"))
    finally:
        broker.dispose()


@pytest.mark.parametrize(
    ("axis", "document_id", "seed", "forged"),
    [
        (
            "clearance",
            "00000000-0000-0000-0000-000000000101",
            {"access_tier": 3},
            "3",
        ),
        (
            "corpora",
            "00000000-0000-0000-0000-000000000102",
            {"corpus": "secret-corpus"},
            "secret-corpus",
        ),
        (
            "classifications",
            "00000000-0000-0000-0000-000000000103",
            {"classification": "internal"},
            "public,internal,restricted",
        ),
        (
            "compartments",
            "00000000-0000-0000-0000-000000000104",
            {"compartments": ("omega",)},
            "omega",
        ),
    ],
)
def test_legacy_guc_cannot_escalate_independent_read_axis(
    axis: str, document_id: str, seed: dict[str, object], forged: str
) -> None:
    _require_boundary()
    reset_database()
    _seed_document(document_id, **seed)
    assert APP_URL and REVIEW_URL
    app = _engine(APP_URL)
    binder = _binder(APP_URL, REVIEW_URL)
    try:
        with app.begin() as connection:
            binder.bind(connection, LOW)
            before = _secure_claims(connection)
            assert _visible(connection, document_id) == 0
            connection.execute(
                text("SELECT pg_catalog.set_config(:name, :value, true)"),
                {"name": f"korpus.{axis}", "value": forged},
            )
            observed = connection.execute(
                text("SELECT current_setting(:name, true)"),
                {"name": f"korpus.{axis}"},
            ).scalar_one()
            assert observed == forged
            assert _secure_claims(connection) == before
            assert _visible(connection, document_id) == 0
    finally:
        binder.close()
        app.dispose()


def test_legacy_roles_guc_cannot_gain_writer_authority() -> None:
    _require_boundary()
    reset_database()
    document_id = "00000000-0000-0000-0000-000000000105"
    _seed_document(document_id)
    assert APP_URL and REVIEW_URL and POSTGRES_ADMIN_URL
    app = _engine(APP_URL)
    binder = _binder(APP_URL, REVIEW_URL)
    try:
        with app.begin() as connection:
            binder.bind(connection, LOW)
            assert _visible(connection, document_id) == 1
            before = _secure_claims(connection)
            connection.execute(
                text("SELECT pg_catalog.set_config('korpus.roles','admin,curator',true)")
            )
            assert _secure_claims(connection) == before
            result = connection.execute(
                text("UPDATE documents SET canonical_title='forged' WHERE id=:id"),
                {"id": document_id},
            )
            assert result.rowcount == 0
        admin = _engine(POSTGRES_ADMIN_URL)
        try:
            with admin.connect() as connection:
                title = connection.execute(
                    text("SELECT canonical_title FROM documents WHERE id=:id"),
                    {"id": document_id},
                ).scalar_one()
            assert title == "protected"
        finally:
            admin.dispose()
    finally:
        binder.close()
        app.dispose()


def test_committed_binding_cannot_leak_into_next_pooled_transaction() -> None:
    _require_boundary()
    reset_database()
    assert APP_URL and REVIEW_URL
    app = _engine(APP_URL)
    binder = _binder(APP_URL, REVIEW_URL)
    try:
        with app.connect() as connection:
            with connection.begin():
                binder.bind(connection, LOW)
                claims = _secure_claims(connection)
                assert claims[0] == 0
                assert list(claims[1]) == ["public-corpus"]
            with connection.begin():
                claims = _secure_claims(connection)
                assert claims[0] == -1
                assert list(claims[1]) == []
                assert list(claims[2]) == []
                assert list(claims[3]) == []
                assert list(claims[4]) == []
    finally:
        binder.close()
        app.dispose()


def test_review_credential_cannot_reanimate_legacy_authorization_gucs() -> None:
    _require_boundary()
    reset_database()
    document_id = "00000000-0000-0000-0000-000000000106"
    _seed_document(
        document_id,
        corpus="secret-corpus",
        access_tier=3,
        classification="restricted",
        compartments=("omega",),
    )
    assert REVIEW_URL and APP_URL
    review = _engine(REVIEW_URL)
    binder = _binder(REVIEW_URL, APP_URL)
    try:
        with review.begin() as connection:
            binder.bind(connection, LOW)
            before = _secure_claims(connection)
            for name, value in (
                ("clearance", "3"),
                ("corpora", "secret-corpus"),
                ("classifications", "public,internal,restricted"),
                ("compartments", "omega"),
                ("roles", "admin,curator,reviewer"),
            ):
                connection.execute(
                    text("SELECT pg_catalog.set_config(:name,:value,true)"),
                    {"name": f"korpus.{name}", "value": value},
                )
            assert _secure_claims(connection) == before
            assert _visible(connection, document_id) == 0
            result = connection.execute(
                text("UPDATE documents SET canonical_title='forged' WHERE id=:id"),
                {"id": document_id},
            )
            assert result.rowcount == 0
    finally:
        binder.close()
        review.dispose()


@pytest.mark.parametrize("tamper", ["backend_start", "login_name"])
def test_broker_rejects_mismatched_backend_incarnation_or_login(tamper: str) -> None:
    _require_boundary()
    reset_database()
    assert APP_URL and IDENTITY_URL
    app = _engine(APP_URL)
    broker = _engine(IDENTITY_URL)
    try:
        with app.begin() as target:
            pid, backend_start, txid, login_name = _target_identity(target)
            if tamper == "backend_start":
                backend_start = backend_start + timedelta(seconds=1)
            else:
                login_name = f"{login_name}_forged"
            with pytest.raises(DBAPIError), broker.begin() as control:
                control.execute(
                    text(
                        "SELECT public.korpus_bind_rls_identity("
                        ":pid,:start,:txid,:login,'forged',3,'secret-corpus',"
                        "'public,internal,restricted','omega','admin,curator')"
                    ),
                    {
                        "pid": pid,
                        "start": backend_start,
                        "txid": txid,
                        "login": login_name,
                    },
                )
    finally:
        app.dispose()
        broker.dispose()


def test_broker_refuses_conflicting_rebind_in_same_transaction() -> None:
    _require_boundary()
    reset_database()
    assert APP_URL and REVIEW_URL and IDENTITY_URL
    app = _engine(APP_URL)
    broker = _engine(IDENTITY_URL)
    binder = _binder(APP_URL, REVIEW_URL)
    try:
        with app.begin() as target:
            binder.bind(target, LOW)
            pid, backend_start, txid, login_name = _target_identity(target)
            before = _secure_claims(target)
            with pytest.raises(DBAPIError), broker.begin() as control:
                control.execute(
                    text(
                        "SELECT public.korpus_bind_rls_identity("
                        ":pid,:start,:txid,:login,'forged',3,'secret-corpus',"
                        "'public,internal,restricted','omega','admin,curator')"
                    ),
                    {
                        "pid": pid,
                        "start": backend_start,
                        "txid": txid,
                        "login": login_name,
                    },
                )
            assert _secure_claims(target) == before
    finally:
        binder.close()
        app.dispose()
        broker.dispose()
