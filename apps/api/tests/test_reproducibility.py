from __future__ import annotations

from apps.api.tests.helpers import approve, ingest_text


def test_corpus_release_changes_only_for_accessible_approved_state(client, public_identity):
    repository = client.app.state.repository
    before = repository.corpus_release_id(
        public_identity, frozenset({"public"}), __import__("datetime").date.today()
    )
    result = ingest_text(client, text="RELEASE-MARKER public evidence.")
    quarantined = repository.corpus_release_id(
        public_identity, frozenset({"public"}), __import__("datetime").date.today()
    )
    approve(client, result["version"]["id"])
    approved = repository.corpus_release_id(
        public_identity, frozenset({"public"}), __import__("datetime").date.today()
    )
    assert before == quarantined
    assert approved != before
