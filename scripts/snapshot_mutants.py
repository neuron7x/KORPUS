"""Surgical first-order mutants for the temporal corpus snapshot invariant."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutant:
    id: str
    path: str
    old: str
    new: str
    control: str
    claim: str


MUTANTS = (
    Mutant(
        "TS01",
        "apps/api/src/korpus/application/snapshot_retrieval.py",
        "        self.snapshot_reader.validate(identity, corpus_ids, as_of, token)\n"
        "        result = self.delegate.search(identity, text, corpus_ids, as_of, limit)\n",
        "        result = self.delegate.search(identity, text, corpus_ids, as_of, limit)\n",
        "apps/api/tests/test_temporal_corpus_snapshot.py::"
        "test_approval_between_token_validation_and_retrieval_fails_closed",
        "pre-read token validation is mandatory",
    ),
    Mutant(
        "TS02",
        "apps/api/src/korpus/application/snapshot_retrieval.py",
        "        result = self.delegate.search(identity, text, corpus_ids, as_of, limit)\n"
        "        self.snapshot_reader.validate(identity, corpus_ids, as_of, token)\n"
        "        return result\n",
        "        result = self.delegate.search(identity, text, corpus_ids, as_of, limit)\n"
        "        return result\n",
        "apps/api/tests/test_temporal_corpus_snapshot.py::"
        "test_rescission_after_retrieval_before_revalidation_fails_closed",
        "post-read token validation is mandatory",
    ),
    Mutant(
        "TS03",
        "apps/api/src/korpus/application/cache.py",
        "                str(token.state_epoch),\n",
        "                \"epoch-omitted\",\n",
        "apps/api/tests/test_query_cache.py::"
        "test_cache_is_bound_to_identity_release_epoch_and_configuration",
        "cache identity includes the monotonic epoch",
    ),
    Mutant(
        "TS04",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        "        if current != token.state_epoch:\n"
        "            raise CorpusConsistencyError(\"corpus state changed after read token capture\")\n",
        "        if False:\n"
        "            raise CorpusConsistencyError(\"corpus state changed after read token capture\")\n",
        "apps/api/tests/test_temporal_corpus_snapshot.py::"
        "test_semantic_backfill_invalidates_an_inflight_snapshot_token",
        "validation rejects stale monotonic epochs",
    ),
    Mutant(
        "TS05",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        "            release_id=digest.hexdigest(),\n",
        "            release_id=digest.hexdigest()[:16],\n",
        "apps/api/tests/test_temporal_corpus_snapshot.py::"
        "test_approval_seals_the_exact_persisted_evidence_set",
        "temporal release identity keeps the full SHA-256 digest",
    ),
    Mutant(
        "TS06",
        "apps/api/src/korpus/infrastructure/corpus_snapshot_guards.py",
        "    \"span_embeddings\",\n",
        "",
        "apps/api/tests/test_temporal_corpus_snapshot.py::"
        "test_semantic_backfill_invalidates_an_inflight_snapshot_token",
        "semantic-index mutations advance corpus state epoch",
    ),
    Mutant(
        "TS07",
        "apps/api/src/korpus/application/corpus_snapshot.py",
        '        _frame(digest, "0" if section is None else f"1:{section}")\n',
        '        _frame(digest, "" if section is None else section)\n',
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_version_evidence_digest_distinguishes_missing_from_empty_section",
        "nullable evidence metadata has a collision-free canonical representation",
    ),
    Mutant(
        "TS08",
        "apps/api/src/korpus/application/answer_snapshot.py",
        "            self.runtime.snapshot_reader.validate(\n"
        "                self.identity, self.corpora, self.query.as_of, self.token\n"
        "            )\n",
        "            pass\n",
        "apps/api/tests/test_answer_snapshot_finish.py::"
        "test_answer_finish_revalidates_after_all_retrieval_work",
        "answer completion revalidates the token after all retrieval/composition work",
    ),
    Mutant(
        "TS09",
        "apps/api/src/korpus/application/answer_snapshot.py",
        "    if any(candidate is not reader for candidate in candidates[1:]):\n"
        "        raise ValueError(\"answer retrieval must share one corpus snapshot reader\")\n",
        "    if False:\n"
        "        raise ValueError(\"answer retrieval must share one corpus snapshot reader\")\n",
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_answer_runtime_rejects_split_snapshot_authorities",
        "answer composition has exactly one snapshot authority",
    ),
    Mutant(
        "TS10",
        "apps/api/src/korpus/application/answer_query.py",
        "        except SnapshotAnswerAbort as abort:\n"
        "            return abort.answer\n",
        "        except SnapshotAnswerAbort:\n"
        "            raise\n",
        "apps/api/tests/test_answer_snapshot_finish.py::"
        "test_capture_failure_returns_audited_fail_closed_answer",
        "snapshot capture failure is returned as a controlled audited abstention",
    ),
    Mutant(
        "TS11",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        "WHERE id IN (OLD.version_id, NEW.version_id) AND evidence_digest IS NOT NULL) ",
        "WHERE id IN (OLD.version_id, NEW.version_id) AND review_state = 'approved') ",
        "apps/api/tests/test_sealed_evidence_immutability.py::"
        "test_rejected_previously_approved_evidence_remains_immutable",
        "sealed spans remain immutable after a later review rejection",
    ),
    Mutant(
        "TS12",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        '                "WHEN OLD.evidence_digest IS NOT NULL "\n',
        '                "WHEN OLD.review_state = \'approved\' "\n',
        "apps/api/tests/test_sealed_evidence_immutability.py::"
        "test_rejected_previously_approved_evidence_remains_immutable",
        "sealed evidence digest remains immutable after a later review rejection",
    ),
    Mutant(
        "TS13",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        "        if token.as_of != as_of:\n"
        "            raise CorpusConsistencyError(\"corpus token historical date does not match the read\")\n",
        "        if False:\n"
        "            raise CorpusConsistencyError(\"corpus token historical date does not match the read\")\n",
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_snapshot_token_cannot_be_reused_for_another_historical_date",
        "snapshot tokens are bound to one historical as_of date",
    ),
    Mutant(
        "TS14",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        "        if token.authorization_scope_id != authorization_scope_id(identity, authorized):\n"
        "            raise CorpusConsistencyError(\n"
        "                \"corpus token authorization identity does not match the read\"\n"
        "            )\n",
        "        if False:\n"
        "            raise CorpusConsistencyError(\n"
        "                \"corpus token authorization identity does not match the read\"\n"
        "            )\n",
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_snapshot_token_cannot_be_reused_under_another_authorization_identity",
        "snapshot tokens are bound to the exact authorization identity",
    ),
    Mutant(
        "TS15",
        "apps/api/src/korpus/application/cache.py",
        "        if cached is not None:\n"
        "            self.snapshot_reader.validate(identity, corpus_ids, as_of, token)\n"
        "            return list(cached)\n",
        "        if cached is not None:\n"
        "            return list(cached)\n",
        "apps/api/tests/test_query_cache.py::"
        "test_cache_never_returns_hit_if_state_changes_during_lookup",
        "cache hits are revalidated after lookup before return",
    ),
    Mutant(
        "TS16",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        "        if before != after:\n"
        "            raise CorpusConsistencyError(\n"
        "                \"corpus state changed while release identity was captured\"\n"
        "            )\n",
        "        if False:\n"
        "            raise CorpusConsistencyError(\n"
        "                \"corpus state changed while release identity was captured\"\n"
        "            )\n",
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_snapshot_capture_rejects_state_change_during_release_projection",
        "release capture rejects state drift between epoch reads",
    ),
    Mutant(
        "TS17",
        "apps/api/src/korpus/application/answer_snapshot.py",
        "        if answer.corpus_release != self.release_id:\n",
        "        if False:\n",
        "apps/api/tests/test_answer_snapshot_finish.py::"
        "test_answer_finish_rejects_a_release_stamp_not_owned_by_the_session",
        "the final answer release stamp must equal the session token release",
    ),
    Mutant(
        "TS18",
        "apps/api/src/korpus/application/answer_audit.py",
        '            "corpus_snapshot": token_audit_record(token),\n',
        '            "corpus_snapshot": None,\n',
        "apps/api/tests/test_answer_snapshot_audit.py::"
        "test_answer_audit_records_the_exact_snapshot_token_and_release",
        "answer audit provenance records the exact snapshot token",
    ),
    Mutant(
        "TS19",
        "apps/api/src/korpus/infrastructure/corpus_snapshot_guards.py",
        "    if missing:\n"
        "        raise RuntimeError(f\"corpus snapshot guard {label} has invalid definition: {missing}\")\n",
        "    if False:\n"
        "        raise RuntimeError(f\"corpus snapshot guard {label} has invalid definition: {missing}\")\n",
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_guard_verification_rejects_correctly_named_noop_trigger",
        "guard verification checks executable semantics, not only trigger names",
    ),
    Mutant(
        "TS20",
        "apps/api/src/korpus/infrastructure/corpus_snapshot_guards.py",
        "        _assert_exact_function_body(name, body, expected_body)\n",
        "        pass\n",
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_postgres_guard_verifier_rejects_dead_code_decoy_body_without_database",
        "PostgreSQL guard functions must match the canonical executable body, not token substrings",
    ),
    Mutant(
        "TS21",
        "apps/api/src/korpus/application/corpus_snapshot.py",
        "    _frame(digest, identity.subject)\n",
        '    _frame(digest, "subject-omitted")\n',
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_snapshot_token_cannot_be_reused_under_another_authorization_identity",
        "authorization scope commits the authenticated subject",
    ),
    Mutant(
        "TS22",
        "apps/api/src/korpus/application/corpus_snapshot.py",
        "    _frame(digest, str(int(identity.clearance)))\n",
        '    _frame(digest, "clearance-omitted")\n',
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_snapshot_token_cannot_be_reused_under_another_authorization_identity",
        "authorization scope commits clearance",
    ),
    Mutant(
        "TS23",
        "apps/api/src/korpus/application/corpus_snapshot.py",
        "        sorted(identity.roles),\n",
        "        (),\n",
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_snapshot_token_cannot_be_reused_under_another_authorization_identity",
        "authorization scope commits roles",
    ),
    Mutant(
        "TS24",
        "apps/api/src/korpus/application/corpus_snapshot.py",
        "        sorted(identity.corpora),\n",
        "        (),\n",
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_snapshot_token_cannot_be_reused_under_another_authorization_identity",
        "authorization scope commits assigned corpora",
    ),
    Mutant(
        "TS25",
        "apps/api/src/korpus/application/corpus_snapshot.py",
        "        sorted(identity.compartments),\n",
        "        (),\n",
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_snapshot_token_cannot_be_reused_under_another_authorization_identity",
        "authorization scope commits need-to-know compartments",
    ),
    Mutant(
        "TS26",
        "apps/api/src/korpus/application/ports.py",
        "    def verify_audit(self) -> AuditVerification: ...\n",
        "    def corpus_release_id(self, identity: Identity, corpus_ids: frozenset[str], as_of: date) -> str: ...\n\n"
        "    def verify_audit(self) -> AuditVerification: ...\n",
        "apps/api/tests/test_corpus_snapshot_contract.py::"
        "test_application_repository_port_cannot_recompute_answer_release",
        "the application repository port exposes no independent release-restamp primitive",
    ),
)
