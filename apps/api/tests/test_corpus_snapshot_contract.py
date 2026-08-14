from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from korpus.application.corpus_snapshot import CorpusReadToken


def _token(release_id: str) -> CorpusReadToken:
    return CorpusReadToken(
        state_epoch=7,
        release_id=release_id,
        as_of=date(2026, 8, 14),
        corpus_ids=frozenset({"public"}),
        authorization_scope_id="b" * 64,
    )


def test_corpus_read_token_accepts_full_sha256_release_identity() -> None:
    token = _token("a" * 64)
    assert token.release_id == "a" * 64


@pytest.mark.parametrize(
    "release_id",
    [
        "a" * 16,
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
    ],
)
def test_corpus_read_token_rejects_truncated_or_noncanonical_release_identity(
    release_id: str,
) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _token(release_id)


def test_guard_verification_binds_trigger_name_to_target_relation(client) -> None:
    """A correctly named trigger on the wrong table is not a temporal guard."""
    reader = client.app.state.corpus_snapshot_reader
    repository = client.app.state.repository
    with repository.engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("DROP TRIGGER trg_documents_epoch_insert"))
            connection.execute(
                text(
                    "CREATE TRIGGER trg_documents_epoch_insert "
                    "AFTER INSERT ON document_versions BEGIN "
                    "UPDATE corpus_state_epoch SET epoch = epoch + 1 WHERE singleton_id = 1; END"
                )
            )
            with pytest.raises(RuntimeError, match="corpus snapshot guards are missing"):
                reader._require_guards(connection)
        finally:
            transaction.rollback()
