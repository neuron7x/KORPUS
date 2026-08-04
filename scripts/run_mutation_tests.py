#!/usr/bin/env python3
"""Deterministic first-order mutation gate for critical KORPUS invariants.

This deliberately mutates security- and evidence-critical predicates and proves
that the focused verification suite kills every mutant. It uses only stdlib and
pytest, so it runs in constrained/offline CI environments.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.provenance import (  # noqa: E402  (path set above)
    PROVENANCE_KEY,
    read_provenance,
    stamp,
)


@dataclass(frozen=True)
class Mutant:
    id: str
    file: str
    old: str
    new: str
    tests: tuple[str, ...]


MUTANTS = (
    Mutant(
        "M01_CLEARANCE_INVERSION",
        "apps/api/src/korpus/application/policy.py",
        "if identity.clearance < document.access_tier:",
        "if identity.clearance > document.access_tier:",
        ("apps/api/tests/test_more_edges.py::test_access_tier_parse_and_document_decision",),
    ),
    Mutant(
        "M02_QUERY_INJECTION_BYPASS",
        "apps/api/src/korpus/application/answer_query.py",
        "if injection.blocked:",
        "if False:",
        ("apps/api/tests/test_answers.py::test_query_control_injection_abstains_before_retrieval",),
    ),
    Mutant(
        "M03_EXACT_SUPPORT_REMOVED",
        "apps/api/src/korpus/application/answer_query.py",
        "support_score = 1.0",
        "support_score = 0.0",
        ("apps/api/tests/test_answers.py::test_approved_document_produces_exact_claim_bound_citation",),
    ),
    Mutant(
        "M04_AUDIT_PREDECESSOR_BYPASS",
        "apps/api/src/korpus/infrastructure/repository.py",
        (
            'if row["previous_hash"] != previous_hash or not hmac.compare_digest(\n'
            '                expected_hash, row["event_hash"]\n'
            '            ):'
        ),
        (
            'if not hmac.compare_digest(\n'
            '                expected_hash, row["event_hash"]\n'
            '            ):'
        ),
        ("apps/api/tests/test_audit.py::test_audit_chain_rejects_re_signed_broken_predecessor_link",),
    ),
    Mutant(
        "M05_SQL_CLEARANCE_FILTER_REMOVED",
        "apps/api/src/korpus/infrastructure/repository.py",
        ".where(documents.c.access_tier <= int(identity.clearance))",
        ".where(documents.c.access_tier <= 3)",
        ("apps/api/tests/test_access_control.py::test_access_tier_is_enforced_in_repository_even_for_public_classification",),
    ),
    Mutant(
        "M06_RELEASE_SCOPE_BROADENED",
        "apps/api/src/korpus/infrastructure/repository.py",
        "retrievable = self.list_retrievable_spans(identity, corpus_ids, as_of)",
        (
            "retrievable = self.list_retrievable_spans("
            "identity.model_copy(update={'clearance': AccessTier.RESTRICTED, "
            "'corpora': frozenset({'public', 'restricted-demo'})}), "
            "frozenset({'public', 'restricted-demo'}), as_of)"
        ),
        ("apps/api/tests/test_access_control.py::test_restricted_corpus_update_does_not_change_public_release",),
    ),
    Mutant(
        "M07_SUPERSESSION_EDGE_DROPPED",
        "apps/api/src/korpus/application/ingestion.py",
        "**version_data.model_dump(),",
        "**version_data.model_dump(exclude={\"supersedes_version_id\"}),",
        ("apps/api/tests/test_versioning.py::test_new_approved_version_supersedes_old_version_in_current_retrieval",),
    ),
    Mutant(
        "M08_OBJECT_HASH_CHECK_REMOVED",
        "apps/api/src/korpus/infrastructure/object_store.py",
        (
            "if hashlib.sha256(content).hexdigest() != source_hash:\n"
            '            raise ValueError("source hash does not match content")'
        ),
        "if False:\n            raise ValueError(\"source hash does not match content\")",
        ("apps/api/tests/test_more_edges.py::test_object_store_is_content_addressed_atomic_and_filename_independent",),
    ),
    Mutant(
        "M09_CLASSIFICATION_GATE_REMOVED",
        "apps/api/src/korpus/application/policy.py",
        "if document.classification.minimum_tier > identity.clearance:",
        "if False:",
        ("apps/api/tests/test_more_edges.py::test_access_tier_parse_and_document_decision",),
    ),
    Mutant(
        "M10_AUDIT_HEAD_CHECK_REMOVED",
        "apps/api/src/korpus/infrastructure/repository.py",
        "if head_sequence != len(rows) or head_hash != previous_hash:",
        "if False:",
        ("apps/api/tests/test_audit.py::test_audit_anchor_detects_tail_truncation",),
    ),
    Mutant(
        "M11_REVIEW_SEPARATION_BYPASS",
        "apps/api/src/korpus/application/ingestion.py",
        "if self.review_separation_required:",
        "if False:",
        ("apps/api/tests/test_state_machine.py::test_controlled_review_separation_is_subject_based",),
    ),
    Mutant(
        "M12_REMOTE_ANCHOR_MAC_BYPASS",
        "apps/api/src/korpus/infrastructure/audit_anchor.py",
        "if not hmac.compare_digest(expected, supplied_mac):",
        "if False:",
        ("apps/api/tests/test_http_audit_anchor.py::test_remote_anchor_detects_payload_tampering",),
    ),
    Mutant(
        "M13_OPERATIONAL_LEAKAGE_GATE_INVERTED",
        "apps/api/src/korpus/application/operations.py",
        '<= int(eval_policy["maximum_leakage_failures"]),',
        '>= int(eval_policy["maximum_leakage_failures"]),',
        ("apps/api/tests/test_operations.py::test_operational_gate_fails_closed_on_trust_regression",),
    ),
    Mutant(
        "M14_SEMANTIC_OUTAGE_FALLBACK",
        "apps/api/src/korpus/application/retrieval.py",
        'raise RetrievalUnavailable("required semantic retrieval is unavailable") from exc',
        'semantic_hits = []',
        ("apps/api/tests/test_semantic_integration.py::test_required_semantic_failure_never_silently_falls_back_to_lexical",),
    ),
    Mutant(
        "M15_TOKEN_PRIVILEGE_TRUST",
        "apps/api/src/korpus/security/entitlements.py",
        "roles=grant.roles,",
        "roles=frozenset(claims.get('roles', grant.roles)),",
        ("apps/api/tests/test_v5_security_kernel.py::test_entitlement_projection_ignores_privileged_token_claims",),
    ),
    Mutant(
        "M16_MALWARE_SCAN_BYPASS",
        "apps/api/src/korpus/application/ingestion.py",
        "self.malware_scanner.scan(path)",
        "None",
        ("apps/api/tests/test_v5_security_kernel.py::test_ingestion_stops_before_parser_when_malware_scanner_rejects",),
    ),
    Mutant(
        "M17_SOURCE_SIGNATURE_BYPASS",
        "apps/api/src/korpus/security/source_authenticity.py",
        (
            "public_key.verify(\n"
            "                signature,\n"
            "                self.signed_payload("
            "issuer=issuer, version=version, source_hash=source_hash),\n"
            "            )"
        ),
        "None",
        ("apps/api/tests/test_v5_security_kernel.py::test_detached_source_signature_binds_content_and_metadata",),
    ),
    Mutant(
        "M18_CALIBRATION_BINDING_BYPASS",
        "apps/api/src/korpus/application/calibration.py",
        "if actual != expected:",
        "if False:",
        ("apps/api/tests/test_calibration.py::test_calibration_profile_and_bound_artifacts_reject_tampering",),
    ),
    Mutant(
        "M19_NEAR_DUPLICATE_ACK_BYPASS",
        "apps/api/src/korpus/infrastructure/repository.py",
        (
            "                    current.near_duplicate_of_version_id is not None\n"
            "                    and not acknowledge_near_duplicate\n"
        ),
        (
            "                    False\n"
            "                    and False\n"
        ),
        ("apps/api/tests/test_near_duplicate_governance.py::test_near_duplicate_requires_explicit_metadata_acknowledgement",),
    ),
    Mutant(
        "M20_EXTRACTION_QUALITY_ACK_BYPASS",
        "apps/api/src/korpus/infrastructure/repository.py",
        "if current.extraction_quality_flags and not acknowledge_extraction_quality:",
        "if False:",
        ("apps/api/tests/test_extraction_quality_governance.py::test_low_quality_extraction_requires_explicit_reviewer_acknowledgement",),
    ),
    Mutant(
        "M21_CSRF_GATE_BYPASS",
        "apps/api/src/korpus/main.py",
        """if (
                    not isinstance(expected_csrf, str)
                    or not supplied_csrf
                    or not csrf_cookie
                    or not secrets.compare_digest(supplied_csrf, expected_csrf)
                    or not secrets.compare_digest(csrf_cookie, expected_csrf)
                ):""",
        "if False:",
        ("apps/api/tests/test_browser_oidc.py::test_browser_oidc_callback_keeps_tokens_http_only_and_enforces_csrf",),
    ),
    Mutant(
        "M22_PARSER_SANDBOX_BYPASS",
        "apps/api/src/korpus/application/ingestion.py",
        "if self.extraction.parser_sandbox_enabled:",
        "if False:",
        ("apps/api/tests/test_v5_security_kernel.py::test_parser_sandbox_setting_selects_isolated_parser",),
    ),
    Mutant(
        "M23_INGESTION_LEASE_BYPASS",
        "apps/api/src/korpus/infrastructure/ingestion_jobs.py",
        "ingestion_jobs.c.lease_expires_at < current,",
        "True,",
        ("apps/api/tests/test_durable_ingestion_jobs.py::test_job_lease_is_exclusive",),
    ),
    Mutant(
        "M24_REVIEWER_REVOCATION_BYPASS",
        "apps/api/src/korpus/security/reviewers.py",
        "if grant.revoked or target not in grant.stages:",
        "if target not in grant.stages:",
        ("apps/api/tests/test_reviewer_registry.py::test_registry_digest_revocation_and_scope_are_fail_closed",),
    ),
    Mutant(
        "M25_REVIEWER_SCOPE_BYPASS",
        "apps/api/src/korpus/security/reviewers.py",
        (
            "                document.corpus_id not in grant.corpora\n"
            "                or version.authority not in grant.authorities\n"
        ),
        (
            "                False\n"
            "                or False\n"
        ),
        ("apps/api/tests/test_reviewer_registry.py::test_registry_digest_revocation_and_scope_are_fail_closed",),
    ),
    Mutant(
        "M26_EXTERNAL_EMBEDDING_EGRESS_BYPASS",
        "apps/api/src/korpus/security/corpus_governance.py",
        "if denied:",
        "if False:",
        ("apps/api/tests/test_corpus_governance.py::test_ingestion_authority_classification_ocr_and_egress_are_governed",),
    ),
    Mutant(
        # Shifts the end of a document's validity by one day. This exact mutation was
        # run against the tree on 2026-08-03 and survived the whole suite: nothing
        # stated which side of the boundary the last day belonged to, so an expired
        # order could still govern an answer and no test objected.
        "M27_VALIDITY_END_BOUNDARY_SHIFT",
        "apps/api/src/korpus/domain/models.py",
        "if self.effective_until is not None and as_of > self.effective_until:",
        "if self.effective_until is not None and as_of >= self.effective_until:",
        ("apps/api/tests/test_validity_boundaries.py::test_a_version_still_governs_on_the_last_day_it_names",),
    ),
    Mutant(
        # The mirror image: rescission is an act, not a term, so its boundary is open
        # on the day it happens. Flipping it would keep a rescinded order in force for
        # one more day.
        "M28_RESCISSION_BOUNDARY_SHIFT",
        "apps/api/src/korpus/domain/models.py",
        "return self.rescinded_at is None or as_of < self.rescinded_at.date()",
        "return self.rescinded_at is None or as_of <= self.rescinded_at.date()",
        ("apps/api/tests/test_validity_boundaries.py::test_a_rescinded_version_stops_governing_on_the_day_of_rescission",),
    ),
    Mutant(
        # The same three boundaries exist a second time, in the SQL that picks
        # candidates. Only the domain copy was defended: a candidate the query drops
        # can never be restored by `_materialize_current`, so this shift expires an
        # order a day early and the domain never gets to disagree.
        "M29_SQL_VALIDITY_END_SHIFT",
        "apps/api/src/korpus/infrastructure/repository.py",
        "AND (v.effective_until IS NULL OR v.effective_until >= :as_of)",
        "AND (v.effective_until IS NULL OR v.effective_until > :as_of)",
        ("apps/api/tests/test_validity_boundaries.py::test_the_search_path_keeps_a_document_on_the_last_day_it_names",),
    ),
    Mutant(
        "M30_SQL_VALIDITY_START_SHIFT",
        "apps/api/src/korpus/infrastructure/repository.py",
        "AND (v.effective_from IS NULL OR v.effective_from <= :as_of)",
        "AND (v.effective_from IS NULL OR v.effective_from < :as_of)",
        ("apps/api/tests/test_validity_boundaries.py::test_sql_and_domain_agree_on_every_day_around_both_bounds",),
    ),
    Mutant(
        "M31_SQL_RESCISSION_SHIFT",
        "apps/api/src/korpus/infrastructure/repository.py",
        "AND (v.rescinded_at IS NULL OR date(v.rescinded_at) > :as_of)",
        "AND (v.rescinded_at IS NULL OR date(v.rescinded_at) >= :as_of)",
        # Behaviourally this one is equivalent — `_materialize_current` re-checks the
        # domain and the answer is unchanged — so only the test that asserts the SQL
        # layer on its own can kill it.
        ("apps/api/tests/test_validity_boundaries.py::test_the_candidate_query_alone_excludes_an_invalid_version",),
    ),
    Mutant(
        # Removes the application-layer scope re-check. Nothing above the retrieval
        # port would object to a row from a corpus the reader never requested.
        "M32_RETRIEVER_CORPUS_RECHECK_REMOVED",
        "apps/api/src/korpus/application/answer_query.py",
        "if document.corpus_id not in corpora:",
        "if False:",
        ("apps/api/tests/test_retriever_scope.py::test_out_of_scope_evidence_stops_the_answer",),
    ),
    Mutant(
        "M33_RETRIEVER_CLEARANCE_RECHECK_REMOVED",
        "apps/api/src/korpus/application/answer_query.py",
        "if not decision.allowed:",
        "if False:",
        ("apps/api/tests/test_retriever_scope.py::test_out_of_scope_evidence_stops_the_answer",),
    ),
    Mutant(
        # Turns the breach into a silent filter — the failure mode the check exists to
        # prevent: the answer looks normal and the defective adapter stays in service.
        "M34_SCOPE_BREACH_DOWNGRADED_TO_FILTER",
        "apps/api/src/korpus/application/answer_query.py",
        (
            "        breaches = self._scope_breaches(identity, corpora, retrieved)\n"
            "        if breaches:"
        ),
        (
            "        breaches = self._scope_breaches(identity, corpora, retrieved)\n"
            "        retrieved = [\n"
            "            item\n"
            "            for item in retrieved\n"
            "            if str(item.version.id) not in {b.version_id for b in breaches}\n"
            "        ]\n"
            "        if False:"
        ),
        ("apps/api/tests/test_retriever_scope.py::test_one_out_of_scope_row_stops_an_otherwise_valid_batch",),
    ),
    Mutant(
        # Restores the ratio that counted citations instead of statements: it exceeds
        # 1.0 whenever a claim carries two citations, and `le=1` turns that into a 500.
        "M35_COVERAGE_COUNTS_CITATIONS_AGAIN",
        "apps/api/src/korpus/application/evidence.py",
        "    coverage = (total - len(unsupported)) / total",
        "    coverage = len(available) / total",
        ("apps/api/tests/test_citation_alignment.py::test_extra_citations_do_not_push_coverage_above_one",),
    ),
    Mutant(
        "M36_MISALIGNMENT_GATE_REMOVED",
        "apps/api/src/korpus/application/answer_query.py",
        "if claims and not support.aligned:",
        "if False:",
        ("apps/api/tests/test_citation_alignment.py::test_a_misaligned_answer_stops_instead_of_raising",),
    ),
    Mutant(
        # Partial credit: a claim with one carried span and one dangling reference
        # would count as supported.
        "M37_PARTIAL_REFERENCE_EARNS_CREDIT",
        "apps/api/src/korpus/application/evidence.py",
        "        missing = referenced.difference(available)",
        (
            "        missing = (\n"
            "            set() if referenced & available else referenced.difference(available)\n"
            "        )"
        ),
        ("apps/api/tests/test_citation_alignment.py::test_partially_valid_references_earn_nothing_for_that_claim",),
    ),
    Mutant(
        # Puts authority back into the convex sum, where a 0.0756 prior gap loses to
        # lexical similarity.
        "M38_AUTHORITY_BACK_TO_A_SCORE_TERM",
        "apps/api/src/korpus/application/retrieval.py",
        (
            "            return (\n"
            "                priors[item.version.authority],\n"
            "                mmr,\n"
        ),
        (
            "            return (\n"
            "                0.0,\n"
            "                mmr,\n"
        ),
        ("apps/api/tests/test_authority_ranking.py::test_similarity_cannot_promote_a_weaker_source_above_a_stronger_one",),
    ),
    Mutant(
        "M39_LOWER_RANK_CAN_VETO_AGAIN",
        "apps/api/src/korpus/application/answer_query.py",
        "        eligible, outranked = self._confine_to_top_authority(eligible)",
        "        outranked: list[RetrievedEvidence] = []",
        ("apps/api/tests/test_authority_ranking.py::test_a_lower_ranked_source_cannot_veto_the_answer",),
    ),
    Mutant(
        "M40_VERSION_CONFLICT_CHECK_REMOVED",
        "apps/api/src/korpus/application/answer_query.py",
        "            if len(version_ids) > 1:",
        "            if False:",
        ("apps/api/tests/test_authority_ranking.py::test_two_live_versions_of_one_document_require_a_human",),
    ),
    Mutant(
        # One version cited twice reads as two independent sources.
        "M41_PER_VERSION_CAP_WIDENED",
        "apps/api/src/korpus/application/retrieval.py",
        "    per_version_cap: int = 1,",
        "    per_version_cap: int = 2,",
        ("apps/api/tests/test_authority_ranking.py::test_one_version_is_selected_once_however_many_spans_match",),
    ),
    Mutant(
        # The same cap, but the value the application is wired with rather than the
        # function default; the two drifted apart before.
        "M43_WIRED_PER_VERSION_CAP_WIDENED",
        "apps/api/src/korpus/api/dependencies.py",
        "        per_version_cap = 1",
        "        per_version_cap = 2",
        ("apps/api/tests/test_authority_ranking.py::test_the_running_configuration_cites_one_span_per_version",),
    ),
    Mutant(
        # Unpadded base64 accepts a second spelling of the same bytes, so a session
        # cookie is not one string.
        "M42_TOKEN_CANONICALITY_CHECK_REMOVED",
        "apps/api/src/korpus/security/browser_oidc.py",
        'if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:',
        "if False:",
        ("apps/api/tests/test_browser_oidc.py::test_the_codec_rejects_a_second_spelling_of_the_same_token",),
    ),
    Mutant(
        # Makes captured material normative — the rule that lived only in prose.
        "M44_ADVERSARY_BECOMES_NORMATIVE",
        "apps/api/src/korpus/domain/models.py",
        "        return self not in {AuthorityClass.ADVERSARY, AuthorityClass.UNKNOWN}",
        "        return self is not AuthorityClass.UNKNOWN",
        ("apps/api/tests/test_governance_boundaries.py::test_an_adversary_source_cannot_be_approved",),
    ),
    Mutant(
        "M45_APPROVER_TIER_DISCARDED",
        "apps/api/src/korpus/application/ingestion.py",
        "            access_tier=transition.access_tier,",
        "            access_tier=None,",
        ("apps/api/tests/test_governance_boundaries.py::test_the_approver_sets_the_access_tier",),
    ),
    Mutant(
        "M46_APPROVER_TIER_ABOVE_CLEARANCE_ALLOWED",
        "apps/api/src/korpus/infrastructure/repository.py",
        "                    if int(access_tier) > int(actor.clearance):",
        "                    if False:",
        ("apps/api/tests/test_governance_boundaries.py::test_an_approver_cannot_assign_a_tier_above_their_own_clearance",),
    ),
    Mutant(
        "M47_DENIED_CORPORA_UNTYPED_AGAIN",
        "apps/api/src/korpus/application/policy.py",
        "            raise UnauthorizedCorporaError(requested, denied)",
        '            raise AuthorizationError("requested corpora exceed identity authorization")',
        ("apps/api/tests/test_governance_boundaries.py::test_an_unheld_corpus_denies_the_request_and_names_which",),
    ),
    Mutant(
        # Deduplication on bytes alone: the re-issue disappears into the version it
        # only resembles.
        "M48_REVISION_IGNORED_IN_DEDUP",
        "apps/api/src/korpus/infrastructure/repository.py",
        (
            "        if revision is not None:\n"
            "            statement = statement.where(versions.c.revision == revision)"
        ),
        (
            "        if False:\n"
            "            statement = statement.where(versions.c.revision == revision)"
        ),
        ("apps/api/tests/test_governance_boundaries.py::test_the_same_bytes_under_a_new_revision_are_a_new_version",),
    ),
    Mutant(
        # Back to a global bound: one subject takes the service.
        "M49_PER_SUBJECT_SHARE_REMOVED",
        "apps/api/src/korpus/application/resilience.py",
        "                if held >= self.per_subject_limit:",
        "                if False:",
        ("apps/api/tests/test_resilience_and_audit_scope.py::test_one_subject_cannot_take_the_whole_service",),
    ),
    Mutant(
        # The share is taken and never returned — a slow denial of service.
        "M50_SUBJECT_SLOT_LEAKED",
        "apps/api/src/korpus/application/resilience.py",
        "            self._release_subject(subject)\n            self._semaphore.release()",
        "            self._semaphore.release()",
        ("apps/api/tests/test_resilience_and_audit_scope.py::test_the_per_subject_share_is_returned_when_the_work_finishes",),
    ),
    Mutant(
        "M51_INTEGRITY_PROBE_REMOVED",
        "apps/api/src/korpus/infrastructure/repository.py",
        "                return self._integrity_ok(connection)",
        "                return True",
        ("apps/api/tests/test_resilience_and_audit_scope.py::test_healthcheck_fails_on_a_corrupt_database",),
    ),
    Mutant(
        # A scoped read that ignores its scope returns another request's events.
        "M52_AUDIT_TRACE_SCOPE_IGNORED",
        "apps/api/src/korpus/infrastructure/repository.py",
        "            .where(audits.c.payload_json.contains(needle))",
        "            .where(audits.c.sequence >= 1)",
        ("apps/api/tests/test_resilience_and_audit_scope.py::test_the_trace_scope_excludes_other_requests",),
    ),
    Mutant(
        "M53_AUDIT_READ_PERMISSION_DROPPED",
        "apps/api/src/korpus/api/routes.py",
        '        policy.require(identity, "audit:read")',
        "        pass",
        ("apps/api/tests/test_resilience_and_audit_scope.py::test_reading_the_audit_requires_the_audit_permission",),
    ),
    Mutant(
        # Restores the seam that manufactured sentences: the tail of one span joined
        # to the head of the next with a space, quoted verbatim with a matching hash.
        "M54_SPAN_SEAM_MANUFACTURES_TEXT",
        "apps/api/src/korpus/infrastructure/extraction.py",
        "            chunk = text[position:end].strip()",
        '            chunk = (text[position:end] + " " + text[end : end + 20]).strip()',
        ("apps/api/tests/test_quote_provenance.py::test_every_span_is_a_slice_of_its_page",),
    ),
    Mutant(
        "M55_QUOTE_SOURCE_CHECK_REMOVED",
        "apps/api/src/korpus/application/answer_query.py",
        "        unsourced = self._unsourced_quotes(eligible, citations)",
        "        unsourced: list[str] = []",
        ("apps/api/tests/test_quote_provenance.py::test_a_quote_absent_from_its_span_stops_the_answer",),
    ),
    Mutant(
        "M56_RESCISSION_STATE_GUARD_REMOVED",
        "apps/api/src/korpus/infrastructure/repository.py",
        "            if current.rescinded_at is not None:",
        "            if False:",
        ("apps/api/tests/test_rescission_and_clock.py::test_withdrawing_twice_is_refused_as_already_withdrawn",),
    ),
    Mutant(
        "M57_RESCISSION_NOT_WRITTEN",
        "apps/api/src/korpus/infrastructure/repository.py",
        "                .values(rescinded_at=stamp, state_version=current.state_version + 1)",
        "                .values(state_version=current.state_version + 1)",
        ("apps/api/tests/test_rescission_and_clock.py::test_an_approved_order_can_be_withdrawn",),
    ),
    Mutant(
        # Back to the host calendar: the answer depends on where the process runs.
        "M58_AS_OF_READS_LOCAL_CLOCK",
        "apps/api/src/korpus/domain/models.py",
        "    as_of: date = Field(default_factory=lambda: datetime.now(UTC).date())",
        "    as_of: date = Field(default_factory=date.today)",
        ("apps/api/tests/test_rescission_and_clock.py::test_the_default_as_of_does_not_depend_on_the_host_timezone",),
    ),
    Mutant(
        "M59_PROVENANCE_DIGEST_NOT_COMPARED",
        "apps/api/src/korpus/application/provenance.py",
        "        if provenance.source_digest != expected_digest:",
        "        if False:",
        (
            "apps/api/tests/test_evidence_provenance.py::test_gate_rejects_evidence_from_a_foreign_tree",
        ),
    ),
    Mutant(
        "M60_GATE_ASSUMES_PROVENANCE_WHEN_ABSENT",
        "apps/api/src/korpus/application/operations.py",
        '            else (False, ("source digest was not supplied to the gate",))',
        "            else (True, ())",
        (
            "apps/api/tests/test_evidence_provenance.py::test_gate_without_a_digest_cannot_pass",
        ),
    ),
    Mutant(
        "M61_MISSING_PROVENANCE_TREATED_AS_VALID",
        "apps/api/src/korpus/application/provenance.py",
        '            reasons.append(f"{name}: {error}")',
        "            pass",
        (
            "apps/api/tests/test_evidence_provenance.py::test_gate_rejects_reports_without_provenance",
        ),
    ),
    Mutant(
        "M62_DIGEST_DROPS_LENGTH_FRAMING",
        "apps/api/src/korpus/application/provenance.py",
        '        hasher.update(len(relative).to_bytes(4, "big"))\n'
        "        hasher.update(relative)\n"
        '        hasher.update(len(content).to_bytes(8, "big"))\n'
        "        hasher.update(content)",
        "        hasher.update(relative)\n        hasher.update(content)",
        (
            "apps/api/tests/test_evidence_provenance.py::test_digest_separates_path_from_content",
        ),
    ),
    Mutant(
        "M63_ZERO_TESTS_COUNTS_AS_A_RUN",
        "apps/api/src/korpus/application/assurance.py",
        '        "tests_executed": executed_tests >= _as_int(settings["minimum_tests"]),',
        '        "tests_executed": True,',
        (
            "apps/api/tests/test_assurance_aggregation.py::test_zero_tests_is_not_a_successful_run",
        ),
    ),
    Mutant(
        "M64_SKIPPED_SUITE_COUNTS_AS_EXECUTED",
        "apps/api/src/korpus/application/assurance.py",
        "    executed_without_skips = executed_tests - max(skipped, 0)",
        "    executed_without_skips = executed_tests",
        (
            "apps/api/tests/test_assurance_aggregation.py::test_a_suite_that_skipped_almost_everything_is_not_a_run",
        ),
    ),
    Mutant(
        "M65_UNEXECUTED_QUALITY_TOOLING_PASSES",
        "apps/api/src/korpus/application/assurance.py",
        '        "quality_tooling_executed": tools_passed,',
        '        "quality_tooling_executed": True,',
        (
            "apps/api/tests/test_assurance_aggregation.py::test_declared_but_unexecuted_tooling_cannot_pass",
        ),
    ),
    Mutant(
        "M66_QUALITY_TOOL_EXIT_CODE_IGNORED",
        "apps/api/src/korpus/application/assurance.py",
        '        and _as_int(recorded_tools[tool].get("exit_code")) == 0',
        "        and True",
        (
            "apps/api/tests/test_assurance_aggregation.py::test_a_tool_reporting_pass_with_a_nonzero_exit_code_is_rejected",
        ),
    ),
    Mutant(
        "M67_AGGREGATOR_IGNORES_EVIDENCE_ORIGIN",
        "apps/api/src/korpus/application/assurance.py",
        '        "evidence_provenance": provenance_ok,',
        '        "evidence_provenance": True,',
        (
            "apps/api/tests/test_assurance_aggregation.py::test_evidence_from_a_foreign_tree_fails_the_aggregate",
        ),
    ),
    Mutant(
        "M68_OVERLAY_PATCHES_SILENTLY_DROPPED",
        "apps/api/src/korpus/application/deployment.py",
        '            raise RenderError(f"{directory}: patch target {target} matches no resource")',
        "            continue",
        (
            "apps/api/tests/test_deployment_overlays.py::test_a_patch_matching_nothing_is_refused",
        ),
    ),
    Mutant(
        "M69_ONLY_BASE_IS_DISCOVERED",
        "apps/api/src/korpus/application/deployment.py",
        '    return sorted(path.parent for path in deploy_root.rglob("kustomization.yaml"))',
        '    return sorted(path.parent for path in deploy_root.glob("kustomization.yaml"))',
        (
            "apps/api/tests/test_deployment_overlays.py::test_the_repository_ships_a_production_overlay_that_is_validated",
        ),
    ),
    Mutant(
        "M70_MUTABLE_ROOT_FILESYSTEM_ACCEPTED",
        "apps/api/src/korpus/application/deployment.py",
        '        if security.get("readOnlyRootFilesystem") is not True:',
        "        if False:",
        (
            "apps/api/tests/test_deployment_overlays.py::test_a_hostile_overlay_patch_is_caught",
        ),
    ),
    Mutant(
        "M71_FLOATING_IMAGE_TAG_ACCEPTED",
        "apps/api/src/korpus/application/deployment.py",
        '        if "@sha256:" not in image:',
        "        if False:",
        (
            "apps/api/tests/test_deployment_overlays.py::test_a_hostile_overlay_patch_is_caught",
        ),
    ),
    Mutant(
        "M72_UNSUPPORTED_KUSTOMIZE_FIELDS_IGNORED",
        "apps/api/src/korpus/application/deployment.py",
        "    unsupported = set(spec) - SUPPORTED_KUSTOMIZATION_FIELDS",
        "    unsupported = set()",
        (
            "apps/api/tests/test_deployment_overlays.py::test_an_unsupported_kustomization_field_is_refused",
        ),
    ),
    Mutant(
        "M73_CITED_EVIDENCE_NOT_OPENED",
        "apps/api/src/korpus/application/evidence_registry.py",
        "        if not path.exists():",
        "        if False:",
        (
            "apps/api/tests/test_evidence_registry.py::test_a_missing_file_is_reported",
        ),
    ),
    Mutant(
        "M74_CITED_TEST_NAME_NOT_RESOLVED",
        "apps/api/src/korpus/application/evidence_registry.py",
        "        if selector not in _defined_names(path):",
        "        if False:",
        (
            "apps/api/tests/test_evidence_registry.py::test_a_deleted_test_inside_an_existing_file_is_reported",
        ),
    ),
    Mutant(
        "M75_PROSE_COUNTS_AS_CLOSURE",
        "apps/api/src/korpus/application/evidence_registry.py",
        "        if statuses.get(finding_id) in executable_statuses and not any(",
        "        if False and not any(",
        (
            "apps/api/tests/test_evidence_registry.py::test_closure_claimed_on_prose_alone_is_rejected",
        ),
    ),
    Mutant(
        "M76_UNCALIBRATED_SCORE_DISCLAIMER_UNGUARDED",
        "apps/web/scripts/validate.mjs",
        'if (!js.includes("Ranking utility не є ймовірністю правильності")) '
        'throw new Error("uncalibrated score disclaimer missing");',
        "",
        (
            "apps/api/tests/test_web_score_presentation.py::test_the_web_validator_enforces_the_disclaimer",
        ),
    ),
    Mutant(
        "M77_SPAN_SELF_REFUTATION_IGNORED",
        "apps/api/src/korpus/application/answer_query.py",
        "                if refutation is not None:",
        "                if False:",
        (
            "apps/api/tests/test_intra_span_contradiction.py::test_a_span_that_reverses_itself_stops_the_answer",
        ),
    ),
    Mutant(
        "M78_REFUTATION_LOOKS_ONLY_AT_SELECTED_SENTENCES",
        "apps/api/src/korpus/application/evidence.py",
        "    for sentence, _start, _end in segment_sentences(evidence_text):",
        "    for sentence, _start, _end in segment_sentences(claim):",
        (
            "apps/api/tests/test_intra_span_contradiction.py::test_a_span_that_reverses_itself_stops_the_answer",
        ),
    ),
    Mutant(
        "M79_REFUTATION_SCAN_NARROWED_TO_CITATIONS",
        "apps/api/src/korpus/application/answer_query.py",
        "            for item in eligible:\n"
        "                refutation = refuting_sentence(claim.text, item.span.text)",
        "            for item in [\n"
        "                found\n"
        "                for found in eligible\n"
        "                if found.span.id in {citation.span_id for citation in citations}\n"
        "            ]:\n"
        "                refutation = refuting_sentence(claim.text, item.span.text)",
        (
            "apps/api/tests/test_intra_span_contradiction.py::test_the_scan_covers_eligible_spans_not_only_cited_ones",
        ),
    ),
    Mutant(
        "M80_NUMERALS_POLLUTE_PROPOSITION_SIMILARITY",
        "apps/api/src/korpus/application/evidence.py",
        "    content = {token for token in tokens.difference(_NEGATIONS) "
        "if not _NUMERAL.fullmatch(token)}",
        "    content = set(tokens.difference(_NEGATIONS))",
        (
            "apps/api/tests/test_intra_span_contradiction.py::test_a_numeric_reversal_inside_one_span_stops_the_answer",
        ),
    ),
    Mutant(
        "M81_NEW_DOCUMENT_MAY_SUPERSEDE_A_FOREIGN_VERSION",
        "apps/api/src/korpus/application/ingestion.py",
        "        if version_data.supersedes_version_id is not None:\n"
        "            # Supersession is an edge inside one canonical document.",
        "        if False:\n"
        "            # Supersession is an edge inside one canonical document.",
        (
            "apps/api/tests/test_foreign_supersession.py::test_a_new_document_cannot_declare_itself_successor_of_another",
        ),
    ),
    Mutant(
        "M82_SQL_HONOURS_A_CROSSING_SUPERSESSION_EDGE",
        "apps/api/src/korpus/infrastructure/repository.py",
        "            .where(superseding.c.document_id == versions.c.document_id)",
        "",
        (
            "apps/api/tests/test_foreign_supersession.py::test_a_crossing_edge_already_in_the_database_is_not_honoured",
        ),
    ),
    Mutant(
        "M83_ENTITLEMENT_CACHE_FROZEN_FOR_PROCESS_LIFETIME",
        "apps/api/src/korpus/security/auth.py",
        "        path, digest, hashlib.sha256(Path(path).read_bytes()).hexdigest()",
        '        path, digest, "constant"',
        (
            "apps/api/tests/test_entitlement_revocation.py::test_revocation_on_disk_denies_the_subject_without_a_restart",
        ),
    ),
)


def copy_repository(destination: Path) -> None:
    ignored = shutil.ignore_patterns(
        ".git",
        ".pytest_cache",
        "__pycache__",
        ".coverage",
        "var",
        "dist",
        "node_modules",
        ".venv",
    )
    shutil.copytree(ROOT, destination, ignore=ignored, dirs_exist_ok=True)


def run_mutant(mutant: Mutant) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"korpus-{mutant.id.lower()}-") as temp:
        sandbox = Path(temp) / "repo"
        copy_repository(sandbox)
        target = sandbox / mutant.file
        original = target.read_text(encoding="utf-8")
        count = original.count(mutant.old)
        if count == 0:
            return {"id": mutant.id, "status": "INVALID", "reason": "mutation target not found"}
        target.write_text(original.replace(mutant.old, mutant.new), encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(sandbox / "apps/api/src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONHASHSEED"] = "0"
        command = [sys.executable, "-m", "pytest", "-q", "--maxfail=1", *mutant.tests]
        completed = subprocess.run(
            command,
            cwd=sandbox,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=45,
            check=False,
        )
        killed = completed.returncode != 0
        return {
            "id": mutant.id,
            "file": mutant.file,
            "status": "KILLED" if killed else "SURVIVED",
            "returncode": completed.returncode,
            "target_occurrences": count,
            "tests": list(mutant.tests),
            "output_tail": completed.stdout[-3000:],
        }


def summarize(
    results: list[dict[str, object]], *, shard_index: int | None, shard_count: int
) -> dict[str, object]:
    killed = sum(result["status"] == "KILLED" for result in results)
    valid = sum(result["status"] in {"KILLED", "SURVIVED"} for result in results)
    score = killed / valid if valid else 0.0
    return {
        "schema_version": 3,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "mutants": len(results),
        "valid_mutants": valid,
        "killed": killed,
        "survived": [result["id"] for result in results if result["status"] == "SURVIVED"],
        "invalid": [result["id"] for result in results if result["status"] == "INVALID"],
        "mutation_score": score,
        # mutation_score divides by the mutants that still *apply*. A mutant whose
        # target line was reformatted stops applying, leaves the denominator, and the
        # score stays 1.0 while the catalogue quietly shrinks — which is exactly what
        # happened on 2026-08-03, when four security mutants (M04, M17, M19, M25) went
        # INVALID after a lint pass rewrapped their lines and the report still read
        # 1.000. The exit code was correct; the number in the artefact was not, and the
        # artefact is what release evidence carries. This second figure divides by the
        # whole catalogue, so an unapplied mutant is visible in the score itself.
        "mutation_score_over_catalogue": killed / len(results) if results else 0.0,
        "results": results,
        PROVENANCE_KEY: stamp(ROOT, "scripts/run_mutation_tests.py"),
    }


def merge_shards(shard_count: int) -> dict[str, object]:
    shard_dir = ROOT / "var/mutation-shards"
    shard_paths = [
        shard_dir / f"shard-{index}-of-{shard_count}.json" for index in range(shard_count)
    ]
    missing = [str(path) for path in shard_paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing mutation shards: {missing}")
    results: list[dict[str, object]] = []
    # Sharding splits the catalogue across processes; nothing but this check stops
    # the merged report from stitching together shards run against different trees
    # (a stale shard left in var/ from an earlier commit merges silently otherwise).
    current_digest = read_provenance({PROVENANCE_KEY: stamp(ROOT, "merge")}).source_digest
    for path in shard_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("shard_count", -1)) != shard_count:
            raise RuntimeError(f"shard count mismatch in {path}")
        shard_digest = read_provenance(payload).source_digest
        if shard_digest != current_digest:
            raise RuntimeError(
                f"shard {path.name} was produced from a different source tree "
                f"({shard_digest[:12]}… != {current_digest[:12]}…)"
            )
        results.extend(payload.get("results", []))
    expected = {mutant.id for mutant in MUTANTS}
    actual = {str(result.get("id")) for result in results}
    if actual != expected or len(results) != len(MUTANTS):
        raise RuntimeError(
            f"mutation shard coverage mismatch: "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    ordered = sorted(results, key=lambda item: str(item["id"]))
    report = summarize(ordered, shard_index=None, shard_count=shard_count)
    report["mutants"] = len(MUTANTS)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--merge", action="store_true")
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="run this many mutants concurrently; each still gets its own copy of the tree",
    )
    parser.add_argument(
        "--only",
        default="",
        help=(
            "comma-separated mutant ids to run as a probe. Writes var/mutation-probe.json "
            "and never var/mutation-report.json: a partial run is a development aid, not "
            "the gate, and must not be able to stand in for one."
        ),
    )
    return parser.parse_args()


def run_selected(mutants: list[Mutant], jobs: int) -> list[dict[str, object]]:
    """Run mutants, preserving catalogue order in the results regardless of jobs.

    Each mutant already works in its own copy of the tree, so concurrency changes
    wall-clock and nothing else. Order is restored explicitly because a report whose
    contents depend on scheduling cannot be compared between runs.
    """

    if jobs <= 1:
        return [run_mutant(mutant) for mutant in mutants]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(run_mutant, mutants))


def main() -> int:
    args = parse_args()
    if args.shard_count < 1:
        raise SystemExit("--shard-count must be >= 1")
    if args.jobs < 1:
        raise SystemExit("--jobs must be >= 1")
    if args.only:
        requested = [name.strip() for name in args.only.split(",") if name.strip()]
        by_id = {mutant.id: mutant for mutant in MUTANTS}
        unknown = [name for name in requested if name not in by_id]
        if unknown:
            raise SystemExit(f"unknown mutant ids: {unknown}")
        results = run_selected([by_id[name] for name in requested], args.jobs)
        report = summarize(results, shard_index=None, shard_count=1)
        report["probe"] = True
        output = ROOT / "var/mutation-probe.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {key: value for key, value in report.items() if key != "results"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if report["mutation_score"] == 1.0 else 1
    if args.merge:
        report = merge_shards(args.shard_count)
        output = ROOT / "var/mutation-report.json"
    else:
        shard_index = 0 if args.shard_index is None else args.shard_index
        if not 0 <= shard_index < args.shard_count:
            raise SystemExit("--shard-index must satisfy 0 <= index < shard-count")
        selected = list(MUTANTS[shard_index::args.shard_count])
        results = run_selected(selected, args.jobs)
        report = summarize(
            results,
            shard_index=shard_index if args.shard_count > 1 else None,
            shard_count=args.shard_count,
        )
        if args.shard_count > 1:
            shard_name = f"shard-{shard_index}-of-{args.shard_count}.json"
            output = ROOT / "var/mutation-shards" / shard_name
        else:
            output = ROOT / "var/mutation-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "results"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    expected = len(MUTANTS) if args.merge or args.shard_count == 1 else len(report["results"])
    return 0 if report["mutation_score"] == 1.0 and report["valid_mutants"] == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
