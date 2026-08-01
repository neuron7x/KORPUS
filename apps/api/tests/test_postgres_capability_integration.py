from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from korpus.domain.models import AccessTier, Identity
from korpus.security.database_capability import DatabaseCapabilityIssuer

ADMIN_URL = os.getenv("KORPUS_POSTGRES_ADMIN_URL")
APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
KEY_FILE = os.getenv("KORPUS_DATABASE_CAPABILITY_KEY_FILE")
KEY_ID = os.getenv("KORPUS_DATABASE_CAPABILITY_KEY_ID", "act25-ephemeral")
pytestmark = pytest.mark.postgres


@pytest.mark.skipif(
    not ADMIN_URL or not APP_URL or not KEY_FILE,
    reason="live PostgreSQL capability environment is not configured",
)
def test_arbitrary_application_sql_cannot_broaden_authority() -> None:
    assert ADMIN_URL is not None and APP_URL is not None and KEY_FILE is not None
    admin = create_engine(ADMIN_URL)
    app = create_engine(APP_URL)
    issuer = DatabaseCapabilityIssuer(KEY_ID, Path(KEY_FILE).read_bytes().strip())
    now = datetime.now(UTC)

    with admin.begin() as connection:
        connection.execute(text("DELETE FROM document_compartments"))
        connection.execute(text("DELETE FROM documents"))
        connection.execute(text("DELETE FROM korpus_auth.consumed_capabilities"))
        connection.execute(
            text(
                "INSERT INTO documents(id,canonical_title,corpus_id,issuer,jurisdiction,"
                "document_type,access_tier,classification,compartments_json,created_at) VALUES "
                "('public-id','Public','public','test','UA','test',0,'public','[]',now()),"
                "('restricted-id','Restricted','restricted-demo','test','UA','test',3,'restricted','[]',now()),"
                "('omega-id','Omega','restricted-demo','test','UA','test',3,'restricted','[\"omega\"]',now())"
            )
        )
        connection.execute(
            text(
                "INSERT INTO document_compartments(document_id,compartment) "
                "VALUES ('omega-id','omega')"
            )
        )

    # Missing capability and the legacy attacker-controlled GUCs reveal no identifiers or counts.
    with app.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0
        for name, value in {
            "korpus.clearance": "3",
            "korpus.corpora": "restricted-demo",
            "korpus.classifications": "restricted",
            "korpus.compartments": "omega",
            "korpus.roles": "admin,curator,user",
        }.items():
            connection.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
        assert connection.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0

    public = Identity(subject="public-user", roles=frozenset({"user"}), corpora=frozenset({"public"}))
    public_token = issuer.issue(
        public,
        jti="public-read-once",
        not_before=now - timedelta(seconds=5),
        expires_at=now + timedelta(seconds=60),
    )
    with app.begin() as connection:
        connection.execute(text("SELECT korpus_auth.activate(:token)"), {"token": public_token})
        assert connection.execute(text("SELECT id FROM documents ORDER BY id")).scalars().all() == [
            "public-id"
        ]

    # A one-transaction capability cannot be replayed.
    with pytest.raises(DBAPIError, match="DBCAP_REPLAYED"):
        with app.begin() as connection:
            connection.execute(text("SELECT korpus_auth.activate(:token)"), {"token": public_token})

    restricted = Identity(
        subject="restricted-user",
        roles=frozenset({"user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"restricted-demo"}),
    )
    unrelated = restricted.model_copy(update={"compartments": frozenset({"other"})})
    authorized = restricted.model_copy(update={"compartments": frozenset({"omega"})})
    for jti, identity, expected in (
        ("restricted-no-compartment", restricted, ["restricted-id"]),
        ("restricted-other-compartment", unrelated, ["restricted-id"]),
        ("restricted-omega", authorized, ["omega-id", "restricted-id"]),
    ):
        token = issuer.issue(
            identity,
            jti=jti,
            not_before=now - timedelta(seconds=5),
            expires_at=now + timedelta(seconds=60),
        )
        with app.begin() as connection:
            connection.execute(text("SELECT korpus_auth.activate(:token)"), {"token": token})
            assert connection.execute(
                text("SELECT id FROM documents ORDER BY id")
            ).scalars().all() == expected

    # Read scope cannot mutate. Explicit write scope can mutate only its visible row.
    read_only = issuer.issue(
        authorized.model_copy(update={"roles": frozenset({"curator"})}),
        jti="read-only",
        not_before=now - timedelta(seconds=5),
        expires_at=now + timedelta(seconds=60),
    )
    with app.begin() as connection:
        connection.execute(text("SELECT korpus_auth.activate(:token)"), {"token": read_only})
        assert connection.execute(
            text("UPDATE documents SET canonical_title='forged' WHERE id='omega-id'")
        ).rowcount == 0
    write = issuer.issue(
        authorized.model_copy(update={"roles": frozenset({"curator"})}),
        jti="authorized-write",
        not_before=now - timedelta(seconds=5),
        expires_at=now + timedelta(seconds=60),
        operations=frozenset({"read", "write"}),
    )
    with app.begin() as connection:
        connection.execute(text("SELECT korpus_auth.activate(:token)"), {"token": write})
        assert connection.execute(
            text("UPDATE documents SET canonical_title='authorized' WHERE id='omega-id'")
        ).rowcount == 1

    tampered = write[:-1] + ("0" if write[-1] != "0" else "1")
    with pytest.raises(DBAPIError, match="DBCAP_INVALID_SIGNATURE"):
        with app.begin() as connection:
            connection.execute(text("SELECT korpus_auth.activate(:token)"), {"token": tampered})

    # The application role cannot inspect verification keys or replay state.
    for statement in (
        "SELECT * FROM korpus_auth.capability_keys",
        "SELECT * FROM korpus_auth.consumed_capabilities",
        "SELECT korpus_auth.verified_payload('attacker')",
    ):
        with pytest.raises(DBAPIError):
            with app.begin() as connection:
                connection.execute(text(statement)).all()

    with admin.begin() as connection:
        connection.execute(text("DELETE FROM document_compartments"))
        connection.execute(text("DELETE FROM documents"))
        connection.execute(text("DELETE FROM korpus_auth.consumed_capabilities"))
    admin.dispose()
    app.dispose()
