from __future__ import annotations

import hashlib
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from korpus.application.answer_snapshot import SnapshotAnswerRuntime, SnapshotAuditPolicy
from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    CorpusReadToken,
    version_evidence_digest,
)
from korpus.domain.models import Identity


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


def test_version_evidence_digest_distinguishes_missing_from_empty_section() -> None:
    content = "same evidence bytes"
    text_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    missing = version_evidence_digest([("span-1", 0, None, None, content, text_hash)])
    empty = version_evidence_digest([("span-1", 0, None, "", content, text_hash)])
    assert missing != empty


def test_snapshot_capture_rejects_state_change_during_release_projection(
    client, admin_identity, monkeypatch
) -> None:
    reader = client.app.state.corpus_snapshot_reader
    epochs = iter((41, 42))
    monkeypatch.setattr(reader, "_epoch", lambda _connection: next(epochs))

    with pytest.raises(CorpusConsistencyError, match="while release identity was captured"):
        reader.capture(admin_identity, frozenset(), date(2026, 8, 14))


def test_snapshot_token_cannot_be_reused_for_another_historical_date(
    client, admin_identity
) -> None:
    reader = client.app.state.corpus_snapshot_reader
    corpora = frozenset({"public"})
    captured_at = date(2026, 8, 14)
    token = reader.capture(admin_identity, corpora, captured_at)

    with pytest.raises(CorpusConsistencyError, match="historical date"):
        reader.validate(admin_identity, corpora, date(2026, 8, 13), token)


def test_snapshot_token_cannot_be_reused_under_another_authorization_identity(
    client, admin_identity
) -> None:
    reader = client.app.state.corpus_snapshot_reader
    corpora = frozenset({"public"})
    as_of = date(2026, 8, 14)
    token = reader.capture(admin_identity, corpora, as_of)
    changed_identity = Identity(
        subject=admin_identity.subject,
        roles=admin_identity.roles | {"snapshot_scope_probe"},
        clearance=admin_identity.clearance,
        corpora=admin_identity.corpora,
        compartments=admin_identity.compartments,
    )

    with pytest.raises(CorpusConsistencyError, match="authorization identity"):
        reader.validate(changed_identity, corpora, as_of, token)


def test_answer_runtime_rejects_split_snapshot_authorities() -> None:
    repository_reader = object()
    retriever_reader = object()
    repository = SimpleNamespace(corpus_snapshot_reader=repository_reader)
    retriever = SimpleNamespace(snapshot_reader=retriever_reader)
    policy = SnapshotAuditPolicy(0.1, 0.1, 0.1, "contract-test")

    with pytest.raises(ValueError, match="share one corpus snapshot reader"):
        SnapshotAnswerRuntime(repository, retriever, policy)  # type: ignore[arg-type]


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
