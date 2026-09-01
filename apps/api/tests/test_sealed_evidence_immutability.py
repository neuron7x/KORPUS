from __future__ import annotations

import hashlib

import pytest
from korpus.infrastructure.schema import spans, versions
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import privileged_connection
from apps.api.tests.helpers import approve, ingest_text, transition


def test_rejected_previously_approved_evidence_remains_immutable(client) -> None:
    created = ingest_text(
        client,
        title="Sealed evidence rejection control",
        text="Evidence sealed by approval must remain immutable after later rejection.",
    )
    version_id = str(created["version"]["id"])
    approve(client, version_id)
    transition(client, version_id, "rejected")

    tampered = "Evidence changed after review rejection."
    tampered_hash = hashlib.sha256(tampered.encode("utf-8")).hexdigest()

    with pytest.raises(DBAPIError), privileged_connection(client) as connection:
        connection.execute(
            update(spans)
            .where(spans.c.version_id == version_id)
            .values(text=tampered, text_hash=tampered_hash)
        )

    with pytest.raises(DBAPIError), privileged_connection(client) as connection:
        connection.execute(
            update(versions).where(versions.c.id == version_id).values(evidence_digest="f" * 64)
        )
