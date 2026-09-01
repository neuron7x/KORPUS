from __future__ import annotations

from apps.api.tests.helpers import approve, ingest_text


def test_corpus_release_changes_only_for_accessible_approved_state(client, public_identity):
    reader = client.app.state.corpus_snapshot_reader
    before = reader.capture(
        public_identity, frozenset({"public"}), __import__("datetime").date.today()
    ).release_id
    result = ingest_text(client, text="RELEASE-MARKER public evidence.")
    quarantined = reader.capture(
        public_identity, frozenset({"public"}), __import__("datetime").date.today()
    ).release_id
    approve(client, result["version"]["id"])
    approved = reader.capture(
        public_identity, frozenset({"public"}), __import__("datetime").date.today()
    ).release_id
    assert before == quarantined
    assert approved != before
