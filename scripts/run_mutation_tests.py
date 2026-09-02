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
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from bounded_process import run_bounded  # noqa: E402
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
    full_copy: bool = False


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
        "            support_score = extractive_support(candidate.text, item.span.text)",
        "            support_score = 0.0",
        (
            "apps/api/tests/test_answers.py::test_approved_document_produces_exact_claim_bound_citation",
        ),
    ),
    Mutant(
        "M04_AUDIT_PREDECESSOR_BYPASS",
        "apps/api/src/korpus/infrastructure/audit_reader.py",
        # Re-anchored 2026-08-07: verification asks the key ring for the key the event
        # names instead of recomputing with whatever the process holds (AUD-003).
        (
            'if row["previous_hash"] != previous_hash or not self.audit_keyring.verify(\n'
            '                signed_by, canonical, str(row["event_hash"])\n'
            "            ):"
        ),
        (
            "if not self.audit_keyring.verify(\n"
            '                signed_by, canonical, str(row["event_hash"])\n'
            "            ):"
        ),
        (
            "apps/api/tests/test_audit.py::test_audit_chain_rejects_re_signed_broken_predecessor_link",
        ),
    ),
    Mutant(
        # Until 2026-08-05 this predicate appeared twice in one file — in the
        # retrieval projection and in `list_documents` — so a single substitution
        # mutated both and one retrieval test killed it. Splitting the projection out
        # left the listing predicate with nothing holding it, and the mutant survived.
        # Two occurrences under one mutant is not two covered call sites.
        "M05_SQL_CLEARANCE_FILTER_REMOVED",
        "apps/api/src/korpus/infrastructure/retrieval_queries.py",
        # Re-anchored 2026-08-06: the predicate moved into `_visibility_filters`, which
        # is now the one place both projections read it from. One occurrence, one mutant.
        "        documents.c.access_tier <= int(identity.clearance),",
        "        documents.c.access_tier <= 3,",
        (
            "apps/api/tests/test_access_control.py::test_access_tier_is_enforced_in_repository_even_for_public_classification",
        ),
    ),
    Mutant(
        # Anchored on the corpus filter above it: the same clearance predicate now
        # appears twice in this file, because `find_near_duplicate` gained the access
        # predicates on 2026-08-06. The parity test caught the ambiguity in the same
        # run that introduced it.
        "M130_LISTING_CLEARANCE_FILTER_REMOVED",
        "apps/api/src/korpus/infrastructure/repository.py",
        "            .where(documents.c.corpus_id.in_(sorted(identity.corpora)))\n"
        "            .where(documents.c.access_tier <= int(identity.clearance))\n"
        "            .where(documents.c.classification.in_(allowed_classifications))",
        "            .where(documents.c.corpus_id.in_(sorted(identity.corpora)))\n"
        "            .where(documents.c.access_tier <= 3)\n"
        "            .where(documents.c.classification.in_(allowed_classifications))",
        (
            "apps/api/tests/test_repository_access_refusals.py::"
            "test_listing_hides_a_document_above_the_readers_clearance",
        ),
    ),
    Mutant(
        "M06_RELEASE_SCOPE_BROADENED",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        # Re-anchored 2026-08-06: the release id is computed from the version projection
        # rather than by materialising every span. The scope it is asked for is what
        # this still mutates.
        # Re-anchored 2026-09-01: релізна тотожність одна, і рахує її читач знімка —
        # `SqlRepository.corpus_release_id` більше не існує. Властивість та сама, дім
        # інший. `type(identity.clearance)` замість імпорту `AccessTier`: мутація не
        # сміє вбиватись NameError'ом, бо тоді вона міряє імпорт, а не гриф.
        (
            "                statement = retrieval_queries.release_projection("
            "identity, authorized, as_of)"
        ),
        (
            "                statement = retrieval_queries.release_projection("
            "identity.model_copy(update={'clearance': type(identity.clearance).RESTRICTED, "
            "'corpora': frozenset({'public', 'restricted-demo'})}), "
            "frozenset({'public', 'restricted-demo'}), as_of)"
        ),
        (
            "apps/api/tests/test_access_control.py::test_restricted_corpus_update_does_not_change_public_release",
        ),
    ),
    Mutant(
        "M07_SUPERSESSION_EDGE_DROPPED",
        "apps/api/src/korpus/application/ingestion.py",
        "**version_data.model_dump(),",
        '**version_data.model_dump(exclude={"supersedes_version_id"}),',
        (
            "apps/api/tests/test_versioning.py::test_new_approved_version_supersedes_old_version_in_current_retrieval",
        ),
    ),
    Mutant(
        "M08_OBJECT_HASH_CHECK_REMOVED",
        "apps/api/src/korpus/infrastructure/object_store.py",
        (
            "if hashlib.sha256(content).hexdigest() != source_hash:\n"
            '            raise ValueError("source hash does not match content")'
        ),
        'if False:\n            raise ValueError("source hash does not match content")',
        (
            "apps/api/tests/test_more_edges.py::test_object_store_is_content_addressed_atomic_and_filename_independent",
        ),
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
        "apps/api/src/korpus/infrastructure/audit_reader.py",
        "if head_sequence != len(rows) or head_hash != previous_hash:",
        "if False:",
        ("apps/api/tests/test_audit.py::test_audit_anchor_detects_tail_truncation",),
    ),
    Mutant(
        "M11_REVIEW_SEPARATION_BYPASS",
        "apps/api/src/korpus/application/ingestion.py",
        "if self.review_separation_required:",
        "if False:",
        (
            "apps/api/tests/test_state_machine.py::test_controlled_review_separation_is_subject_based",
        ),
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
        "apps/api/src/korpus/application/operational_math.py",
        '        "access_noninterference": _count_at_most(',
        '        "access_noninterference": _count_at_least(',
        (
            "apps/api/tests/test_operations.py::test_operational_gate_fails_closed_on_trust_regression",
        ),
    ),
    Mutant(
        "M14_SEMANTIC_OUTAGE_FALLBACK",
        "apps/api/src/korpus/application/retrieval_execution.py",
        '        raise ExecutionUnavailable("required semantic retrieval is unavailable") from exc',
        "        hits = []",
        (
            "apps/api/tests/test_semantic_integration.py::test_required_semantic_failure_never_silently_falls_back_to_lexical",
        ),
    ),
    Mutant(
        "M15_TOKEN_PRIVILEGE_TRUST",
        "apps/api/src/korpus/security/entitlements.py",
        "roles=grant.roles,",
        "roles=frozenset(claims.get('roles', grant.roles)),",
        (
            "apps/api/tests/test_v5_security_kernel.py::test_entitlement_projection_ignores_privileged_token_claims",
        ),
    ),
    Mutant(
        # `self.malware_scanner.scan(path)` appears on both ingestion paths — a new
        # document, and a new version of an existing one. One mutant replaced both,
        # so a test covering either answered for the pair and the other site was
        # never individually falsified. Split 2026-08-06; M181 is the version path.
        "M16_MALWARE_SCAN_BYPASS",
        "apps/api/src/korpus/application/ingestion.py",
        "                    duplicate=True,\n                )\n"
        "        self.malware_scanner.scan(path)",
        "                    duplicate=True,\n                )\n        None",
        (
            "apps/api/tests/test_v5_security_kernel.py::test_ingestion_stops_before_parser_when_malware_scanner_rejects",
        ),
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
        (
            "apps/api/tests/test_v5_security_kernel.py::test_detached_source_signature_binds_content_and_metadata",
        ),
    ),
    Mutant(
        "M18_CALIBRATION_BINDING_BYPASS",
        "apps/api/src/korpus/application/calibration.py",
        "if actual != expected:",
        "if False:",
        (
            "apps/api/tests/test_calibration.py::test_calibration_profile_and_bound_artifacts_reject_tampering",
        ),
    ),
    Mutant(
        "M19_NEAR_DUPLICATE_ACK_BYPASS",
        "apps/api/src/korpus/infrastructure/review_transitions.py",
        (
            "        if current.near_duplicate_of_version_id is not None and not acknowledge_near_duplicate:"
        ),
        ("        if False and False:"),
        (
            "apps/api/tests/test_near_duplicate_governance.py::test_near_duplicate_requires_explicit_metadata_acknowledgement",
        ),
    ),
    Mutant(
        "M20_EXTRACTION_QUALITY_ACK_BYPASS",
        "apps/api/src/korpus/infrastructure/review_transitions.py",
        "if current.extraction_quality_flags and not acknowledge_extraction_quality:",
        "if False:",
        (
            "apps/api/tests/test_extraction_quality_governance.py::test_low_quality_extraction_requires_explicit_reviewer_acknowledgement",
        ),
    ),
    Mutant(
        "M21_CSRF_GATE_BYPASS",
        "apps/api/src/korpus/security/browser_csrf.py",
        'return None if valid else (403, "CSRF validation failed")',
        "return None",
        (
            "apps/api/tests/test_browser_oidc.py::test_global_browser_csrf_gate_refuses_missing_double_submit_material",
        ),
    ),
    Mutant(
        # The decision moved behind the Extractor port on 2026-08-06. It is now a value
        # travelling to an adapter, so the mutant sets the value rather than skipping a
        # branch — and the adapter's half has its own mutant below.
        "M22_PARSER_SANDBOX_BYPASS",
        "apps/api/src/korpus/application/ingestion.py",
        "            sandboxed=self.extraction.parser_sandbox_enabled,",
        "            sandboxed=False,",
        (
            "apps/api/tests/test_v5_security_kernel.py::test_parser_sandbox_setting_selects_isolated_parser",
        ),
    ),
    Mutant(
        "M172_EXTRACTION_ADAPTER_IGNORES_THE_SANDBOX_FLAG",
        "apps/api/src/korpus/infrastructure/extraction.py",
        "        if sandboxed:",
        "        if False:",
        (
            "apps/api/tests/test_v5_security_kernel.py::"
            "test_the_extraction_adapter_runs_the_isolated_parser_when_told_to",
        ),
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
        (
            "apps/api/tests/test_reviewer_registry.py::test_registry_digest_revocation_and_scope_are_fail_closed",
        ),
    ),
    Mutant(
        "M25_REVIEWER_SCOPE_BYPASS",
        "apps/api/src/korpus/security/reviewers.py",
        (
            "                document.corpus_id not in grant.corpora\n"
            "                or version.authority not in grant.authorities\n"
        ),
        ("                False\n                or False\n"),
        (
            "apps/api/tests/test_reviewer_registry.py::test_registry_digest_revocation_and_scope_are_fail_closed",
        ),
    ),
    Mutant(
        "M26_EXTERNAL_EMBEDDING_EGRESS_BYPASS",
        "apps/api/src/korpus/security/corpus_governance.py",
        "if denied:",
        "if False:",
        (
            "apps/api/tests/test_corpus_governance.py::test_ingestion_authority_classification_ocr_and_egress_are_governed",
        ),
    ),
    Mutant(
        # Shifts the end of a document's validity by one day. This exact mutation was
        # run against the tree on 2026-08-03 and survived the whole suite: nothing
        # stated which side of the boundary the last day belonged to, so an expired
        # order could still govern an answer and no test objected.
        "M27_VALIDITY_END_BOUNDARY_SHIFT",
        "apps/api/src/korpus/domain/temporal.py",
        "    if effective_until is not None and effective_until < as_of:",
        "    if effective_until is not None and effective_until <= as_of:",
        (
            "apps/api/tests/test_validity_boundaries.py::test_a_version_still_governs_on_the_last_day_it_names",
        ),
    ),
    Mutant(
        # The mirror image: rescission is an act, not a term, so its boundary is open
        # on the day it happens. Flipping it would keep a rescinded order in force for
        # one more day.
        "M28_RESCISSION_BOUNDARY_SHIFT",
        "apps/api/src/korpus/domain/temporal.py",
        "    if rescinded_at is not None and rescinded_at.date() <= as_of:",
        "    if rescinded_at is not None and rescinded_at.date() < as_of:",
        (
            "apps/api/tests/test_validity_boundaries.py::test_a_rescinded_version_stops_governing_on_the_day_of_rescission",
        ),
    ),
    Mutant(
        # The same three boundaries exist a second time, in the SQL that picks
        # candidates. Only the domain copy was defended: a candidate the query drops
        # can never be restored by `_materialize_current`, so this shift expires an
        # order a day early and the domain never gets to disagree.
        "M29_SQL_VALIDITY_END_SHIFT",
        "apps/api/src/korpus/infrastructure/retrieval_candidate_query.py",
        "              AND (v.effective_until IS NULL OR v.effective_until >= :as_of)\n"
        "              AND (v.rescinded_at IS NULL OR date(v.rescinded_at) > :as_of)",
        "              AND (v.effective_until IS NULL OR v.effective_until > :as_of)\n"
        "              AND (v.rescinded_at IS NULL OR date(v.rescinded_at) > :as_of)",
        (
            "apps/api/tests/test_validity_boundaries.py::test_the_search_path_keeps_a_document_on_the_last_day_it_names",
        ),
    ),
    Mutant(
        "M30_SQL_VALIDITY_START_SHIFT",
        "apps/api/src/korpus/infrastructure/retrieval_candidate_query.py",
        "              {compartment_clause}\n"
        "              AND COALESCE(v.effective_from, v.publication_date) <= :as_of",
        "              {compartment_clause}\n"
        "              AND COALESCE(v.effective_from, v.publication_date) < :as_of",
        (
            "apps/api/tests/test_validity_boundaries.py::test_sql_and_domain_agree_on_every_day_around_both_bounds",
        ),
    ),
    Mutant(
        "M31_SQL_RESCISSION_SHIFT",
        "apps/api/src/korpus/infrastructure/retrieval_candidate_query.py",
        "              AND (v.rescinded_at IS NULL OR date(v.rescinded_at) > :as_of)\n"
        "              AND (v.id, v.document_id) NOT IN (SELECT id, document_id FROM superseded)",
        "              AND (v.rescinded_at IS NULL OR date(v.rescinded_at) >= :as_of)\n"
        "              AND (v.id, v.document_id) NOT IN (SELECT id, document_id FROM superseded)",
        # Behaviourally this one is equivalent — `_materialize_current` re-checks the
        # domain and the answer is unchanged — so only the test that asserts the SQL
        # layer on its own can kill it.
        (
            "apps/api/tests/test_validity_boundaries.py::test_the_candidate_query_alone_excludes_an_invalid_version",
        ),
    ),
    Mutant(
        "M32_RETRIEVER_CORPUS_RECHECK_REMOVED",
        "apps/api/src/korpus/application/answer_analysis.py",
        "if document.corpus_id not in corpora:",
        "if False:",
        ("apps/api/tests/test_retriever_scope.py::test_out_of_scope_evidence_stops_the_answer",),
    ),
    Mutant(
        "M33_RETRIEVER_CLEARANCE_RECHECK_REMOVED",
        "apps/api/src/korpus/application/answer_analysis.py",
        "if not decision.allowed:",
        "if False:",
        ("apps/api/tests/test_retriever_scope.py::test_out_of_scope_evidence_stops_the_answer",),
    ),
    Mutant(
        # Turns the breach into a silent filter — the failure mode the check exists to
        # prevent: the answer looks normal and the defective adapter stays in service.
        "M34_SCOPE_BREACH_DOWNGRADED_TO_FILTER",
        "apps/api/src/korpus/application/answer_retrieval_gate.py",
        ("    breaches = service._scope_breaches(identity, corpora, retrieved)\n    if breaches:"),
        (
            "    breaches = service._scope_breaches(identity, corpora, retrieved)\n"
            "    retrieved = [\n"
            "        item\n"
            "        for item in retrieved\n"
            "        if str(item.version.id) not in {b.version_id for b in breaches}\n"
            "    ]\n"
            "    if False:"
        ),
        (
            "apps/api/tests/test_retriever_scope.py::test_one_out_of_scope_row_stops_an_otherwise_valid_batch",
        ),
    ),
    Mutant(
        # Restores the ratio that counted citations instead of statements: it exceeds
        # 1.0 whenever a claim carries two citations, and `le=1` turns that into a 500.
        "M35_COVERAGE_COUNTS_CITATIONS_AGAIN",
        "apps/api/src/korpus/application/evidence.py",
        "    coverage = (total - len(unsupported)) / total",
        "    coverage = len(available) / total",
        (
            "apps/api/tests/test_citation_alignment.py::test_extra_citations_do_not_push_coverage_above_one",
        ),
    ),
    Mutant(
        "M36_MISALIGNMENT_GATE_REMOVED",
        "apps/api/src/korpus/application/answer_query.py",
        "if claims and not support.aligned:",
        "if False:",
        (
            "apps/api/tests/test_citation_alignment.py::test_a_misaligned_answer_stops_instead_of_raising",
        ),
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
        (
            "apps/api/tests/test_citation_alignment.py::test_partially_valid_references_earn_nothing_for_that_claim",
        ),
    ),
    Mutant(
        # Puts authority back into the convex sum, where a 0.0756 prior gap loses to
        # lexical similarity.
        "M38_AUTHORITY_BACK_TO_A_SCORE_TERM",
        "apps/api/src/korpus/application/retrieval.py",
        ("                authority_tier(item, priors, tier_floor),\n                mmr,\n"),
        ("                0.0,\n                mmr,\n"),
        (
            "apps/api/tests/test_authority_ranking.py::test_similarity_cannot_promote_a_weaker_source_above_a_stronger_one",
        ),
    ),
    Mutant(
        "M39_LOWER_RANK_CAN_VETO_AGAIN",
        "apps/api/src/korpus/application/answer_query.py",
        "        eligible, outranked = self._confine_to_top_authority(eligible)",
        "        outranked: list[RetrievedEvidence] = []",
        (
            "apps/api/tests/test_authority_ranking.py::test_a_lower_ranked_source_cannot_veto_the_answer",
        ),
    ),
    Mutant(
        "M40_VERSION_CONFLICT_CHECK_REMOVED",
        "apps/api/src/korpus/application/answer_analysis.py",
        "        if len(version_ids) > 1:",
        "        if False:",
        (
            "apps/api/tests/test_authority_ranking.py::test_two_live_versions_of_one_document_require_a_human",
        ),
    ),
    Mutant(
        # One version cited twice reads as two independent sources.
        # Declared twice: on `diversify_evidence` and on the retriever that calls it.
        # One mutant widened both, so a test of either answered for the pair.
        # M182 is the retriever's own default.
        "M41_PER_VERSION_CAP_WIDENED",
        "apps/api/src/korpus/application/retrieval.py",
        "    diversity_lambda: float = 0.82,\n    per_version_cap: int = 1,",
        "    diversity_lambda: float = 0.82,\n    per_version_cap: int = 2,",
        (
            "apps/api/tests/test_authority_ranking.py::test_one_version_is_selected_once_however_many_spans_match",
        ),
    ),
    Mutant(
        # The same cap, but the value the application is wired with rather than the
        # function default; the two drifted apart before.
        "M43_WIRED_PER_VERSION_CAP_WIDENED",
        "apps/api/src/korpus/api/dependencies.py",
        "        per_version_cap = 1",
        "        per_version_cap = 2",
        (
            "apps/api/tests/test_authority_ranking.py::test_the_running_configuration_cites_one_span_per_version",
        ),
    ),
    Mutant(
        # Unpadded base64 accepts a second spelling of the same bytes, so a session
        # cookie is not one string.
        "M42_TOKEN_CANONICALITY_CHECK_REMOVED",
        "apps/api/src/korpus/security/browser_oidc.py",
        'if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:',
        "if False:",
        (
            "apps/api/tests/test_browser_oidc.py::test_the_codec_rejects_a_second_spelling_of_the_same_token",
        ),
    ),
    Mutant(
        # Makes captured material normative — the rule that lived only in prose.
        "M44_ADVERSARY_BECOMES_NORMATIVE",
        "apps/api/src/korpus/domain/models.py",
        "        return self not in {AuthorityClass.ADVERSARY, AuthorityClass.UNKNOWN}",
        "        return self is not AuthorityClass.UNKNOWN",
        (
            "apps/api/tests/test_governance_boundaries.py::test_an_adversary_source_cannot_be_approved",
        ),
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
        "apps/api/src/korpus/infrastructure/review_transitions.py",
        "    if int(access_tier) > int(actor.clearance):",
        "    if False:",
        (
            "apps/api/tests/test_governance_boundaries.py::test_an_approver_cannot_assign_a_tier_above_their_own_clearance",
        ),
    ),
    Mutant(
        "M47_DENIED_CORPORA_UNTYPED_AGAIN",
        "apps/api/src/korpus/application/policy.py",
        "            raise UnauthorizedCorporaError(requested, denied)",
        '            raise AuthorizationError("requested corpora exceed identity authorization")',
        (
            "apps/api/tests/test_governance_boundaries.py::test_an_unheld_corpus_denies_the_request_and_names_which",
        ),
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
        (
            "apps/api/tests/test_governance_boundaries.py::test_the_same_bytes_under_a_new_revision_are_a_new_version",
        ),
    ),
    Mutant(
        # Back to a global bound: one subject takes the service.
        "M49_PER_SUBJECT_SHARE_REMOVED",
        "apps/api/src/korpus/application/resilience.py",
        "                if held >= self.per_subject_limit:",
        "                if False:",
        (
            "apps/api/tests/test_resilience_and_audit_scope.py::test_one_subject_cannot_take_the_whole_service",
        ),
    ),
    Mutant(
        # The share is taken and never returned — a slow denial of service.
        "M50_SUBJECT_SLOT_LEAKED",
        "apps/api/src/korpus/application/resilience.py",
        "            self._release_subject(subject)\n            self._semaphore.release()",
        "            self._semaphore.release()",
        (
            "apps/api/tests/test_resilience_and_audit_scope.py::test_the_per_subject_share_is_returned_when_the_work_finishes",
        ),
    ),
    Mutant(
        "M51_INTEGRITY_PROBE_REMOVED",
        "apps/api/src/korpus/infrastructure/repository.py",
        "                return self._integrity_ok(connection)",
        "                return True",
        (
            "apps/api/tests/test_resilience_and_audit_scope.py::test_healthcheck_fails_on_a_corrupt_database",
        ),
    ),
    Mutant(
        # A scoped read that ignores its scope returns another request's events.
        "M52_AUDIT_TRACE_SCOPE_IGNORED",
        "apps/api/src/korpus/infrastructure/audit_reader.py",
        "            .where(self._audits.c.payload_json.contains(needle))",
        "            .where(self._audits.c.sequence >= 1)",
        (
            "apps/api/tests/test_resilience_and_audit_scope.py::test_the_trace_scope_excludes_other_requests",
        ),
    ),
    Mutant(
        "M53_AUDIT_READ_PERMISSION_DROPPED",
        "apps/api/src/korpus/api/routes_audit.py",
        '        policy.require(identity, "audit:read")',
        "        pass",
        (
            "apps/api/tests/test_resilience_and_audit_scope.py::test_reading_the_audit_requires_the_audit_permission",
        ),
    ),
    Mutant(
        # Restores the seam that manufactured sentences: the tail of one span joined
        # to the head of the next with a space, quoted verbatim with a matching hash.
        "M54_SPAN_SEAM_MANUFACTURES_TEXT",
        "apps/api/src/korpus/infrastructure/extraction.py",
        "            chunk = raw.strip()",
        '            chunk = (raw + " " + text[end : end + 20]).strip()',
        ("apps/api/tests/test_quote_provenance.py::test_every_span_is_a_slice_of_its_page",),
    ),
    Mutant(
        "M55_QUOTE_SOURCE_CHECK_REMOVED",
        "apps/api/src/korpus/application/answer_query.py",
        "        unsourced = self._unsourced_quotes(eligible, citations)",
        "        unsourced: list[str] = []",
        (
            "apps/api/tests/test_quote_provenance.py::test_a_quote_absent_from_its_span_stops_the_answer",
        ),
    ),
    Mutant(
        "M56_RESCISSION_STATE_GUARD_REMOVED",
        "apps/api/src/korpus/infrastructure/repository.py",
        "            if current.rescinded_at is not None:",
        "            if False:",
        (
            "apps/api/tests/test_rescission_and_clock.py::test_withdrawing_twice_is_refused_as_already_withdrawn",
        ),
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
        (
            "apps/api/tests/test_rescission_and_clock.py::test_the_default_as_of_does_not_depend_on_the_host_timezone",
        ),
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
        ("apps/api/tests/test_evidence_provenance.py::test_gate_without_a_digest_cannot_pass",),
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
        '        with path.open("rb") as handle:\n'
        "            expected_size = path.stat().st_size\n"
        '            hasher.update(expected_size.to_bytes(8, "big"))',
        "        hasher.update(relative)\n"
        '        with path.open("rb") as handle:\n'
        "            expected_size = path.stat().st_size",
        ("apps/api/tests/test_evidence_provenance.py::test_digest_separates_path_from_content",),
    ),
    Mutant(
        "M63_ZERO_TESTS_COUNTS_AS_A_RUN",
        "apps/api/src/korpus/application/assurance.py",
        '        "tests_executed": executed_tests >= _as_int(settings["minimum_tests"]),',
        '        "tests_executed": True,',
        ("apps/api/tests/test_assurance_aggregation.py::test_zero_tests_is_not_a_successful_run",),
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
        ("apps/api/tests/test_deployment_overlays.py::test_a_patch_matching_nothing_is_refused",),
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
        # Moved with the invariants to kubernetes_requirements.py on 2026-08-05. The
        # predicate is stated positively there, so the mutant is `True` rather than
        # `False`: a requirement that always holds is the same defect as a check that
        # never fires.
        "M70_MUTABLE_ROOT_FILESYSTEM_ACCEPTED",
        "apps/api/src/korpus/kubernetes_requirements.py",
        '            holds=lambda context: security.get("readOnlyRootFilesystem") is True,',
        "            holds=lambda context: True,",
        ("apps/api/tests/test_deployment_overlays.py::test_a_hostile_overlay_patch_is_caught",),
    ),
    Mutant(
        "M71_FLOATING_IMAGE_TAG_ACCEPTED",
        "apps/api/src/korpus/kubernetes_requirements.py",
        '            holds=lambda context: "@sha256:" in image,',
        "            holds=lambda context: True,",
        ("apps/api/tests/test_deployment_overlays.py::test_a_hostile_overlay_patch_is_caught",),
    ),
    Mutant(
        "M134_DROPPED_CAPABILITY_SUBSET_ACCEPTED",
        "apps/api/src/korpus/kubernetes_requirements.py",
        '            holds=lambda context: security.get("capabilities", {}).get("drop")'
        ' == ["ALL"],',
        "            holds=lambda context: True,",
        (
            "apps/api/tests/test_deployment_rendering_refusals.py::"
            "test_a_container_that_loosens_its_own_context_is_reported",
        ),
    ),
    Mutant(
        "M135_EMPTY_RENDER_TREATED_AS_CLEAN",
        "apps/api/src/korpus/kubernetes_requirements.py",
        "            holds=lambda context: bool(context.documents),",
        "            holds=lambda context: True,",
        (
            "apps/api/tests/test_requirement_registry.py::"
            "test_an_empty_render_reports_one_failure_rather_than_the_whole_register",
        ),
    ),
    Mutant(
        "M136_MISSING_RESOURCE_KINDS_IGNORED",
        "apps/api/src/korpus/kubernetes_requirements.py",
        "            holds=lambda context: not (REQUIRED_KINDS - set(context.by_kind)),",
        "            holds=lambda context: True,",
        ("apps/api/tests/test_deployment_overlays.py::test_missing_workloads_are_reported",),
    ),
    Mutant(
        # Survived its first probe against
        # test_the_kubernetes_register_states_the_same_rules_as_the_gate, which counted
        # the config requirements and asserted the base deployment passes. A register
        # can name every key and still assert nothing about their values.
        "M137_PRODUCTION_CONFIG_NOT_REQUIRED",
        "apps/api/src/korpus/kubernetes_requirements.py",
        "        return lambda context: context.config.get(key) == value",
        "        return lambda context: True",
        (
            "apps/api/tests/test_requirement_registry.py::"
            "test_a_deployed_configuration_that_drifts_from_policy_is_reported",
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
        ("apps/api/tests/test_evidence_registry.py::test_a_missing_file_is_reported",),
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
        'if (!app.includes("Якість ранжування не є ймовірністю правильності")) '
        'throw new Error("uncalibrated score disclaimer missing");',
        "",
        (
            "apps/api/tests/test_web_score_presentation.py::test_the_web_validator_enforces_the_disclaimer",
        ),
    ),
    Mutant(
        "M77_SPAN_SELF_REFUTATION_IGNORED",
        "apps/api/src/korpus/application/answer_analysis.py",
        "            if refutation is not None:",
        "            if False:",
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
        "apps/api/src/korpus/application/answer_analysis.py",
        "        for item in eligible:\n            refutation = refuting_sentence(claim.text, item.span.text)",
        "        for item in [\n            found\n            for found in eligible\n            if found.span.id in {citation.span_id for citation in citations}\n        ]:\n            refutation = refuting_sentence(claim.text, item.span.text)",
        (
            "apps/api/tests/test_intra_span_contradiction.py::test_the_scan_covers_eligible_spans_not_only_cited_ones",
        ),
    ),
    Mutant(
        "M80_NUMERALS_POLLUTE_PROPOSITION_SIMILARITY",
        "apps/api/src/korpus/application/evidence.py",
        "    content = {\n        token\n        for token in tokens.difference(_NEGATIONS)\n        if not _NUMERAL.fullmatch(token) and token not in _UNIT_TOKENS\n    }",
        "    content = {token for token in tokens.difference(_NEGATIONS) if token not in _UNIT_TOKENS}",
        (
            "apps/api/tests/test_intra_span_contradiction.py::test_a_numeric_reversal_inside_one_span_stops_the_answer",
        ),
    ),
    Mutant(
        "M81_NEW_DOCUMENT_MAY_SUPERSEDE_A_FOREIGN_VERSION",
        "apps/api/src/korpus/application/ingestion.py",
        "        if version_data.supersedes_version_id is not None:\n"
        "            # Supersession is an edge inside one canonical document.",
        "        if False:\n            # Supersession is an edge inside one canonical document.",
        (
            "apps/api/tests/test_foreign_supersession.py::test_a_new_document_cannot_declare_itself_successor_of_another",
        ),
    ),
    Mutant(
        "M82_SQL_HONOURS_A_CROSSING_SUPERSESSION_EDGE",
        "apps/api/src/korpus/infrastructure/retrieval_queries.py",
        "        .where(superseding.c.document_id == versions.c.document_id)",
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
    Mutant(
        "M84_LEAKAGE_DENOMINATOR_NOT_REQUIRED_BY_GATE",
        "apps/api/src/korpus/application/operational_math.py",
        '        "access_noninterference_measured": _count_at_least(\n            evaluation.get("leakage_checks"), eval_policy.get("minimum_leakage_checks")\n        ),',
        '        "access_noninterference_measured": True,',
        (
            "apps/api/tests/test_leakage_measurement.py::test_the_gate_fails_when_the_metric_had_nothing_to_measure",
        ),
    ),
    Mutant(
        "M85_WITHHELD_SET_COMPUTED_AS_EMPTY",
        "apps/api/src/korpus/application/noninterference.py",
        "        if span.id not in visible",
        "        if False",
        (
            "apps/api/tests/test_noninterference_measurement.py::test_the_withheld_set_is_not_empty_for_a_subject_who_cannot_see_everything",
        ),
    ),
    Mutant(
        "M86_QUOTED_WITHHELD_TEXT_NOT_A_LEAK",
        "apps/api/src/korpus/application/noninterference.py",
        "        if item.text and any(citation.quote in item.text for citation in citations):",
        "        if False:",
        (
            "apps/api/tests/test_noninterference_measurement.py::test_an_answer_quoting_withheld_text_is_recognised_as_a_leak",
        ),
    ),
    Mutant(
        "M87_WITHHELD_IDENTIFIERS_NOT_SEARCHED",
        "apps/api/src/korpus/application/noninterference.py",
        "            if identifier in serialized_answer:",
        "            if False:",
        (
            "apps/api/tests/test_noninterference_measurement.py::test_an_answer_naming_a_withheld_identifier_is_recognised_as_a_leak",
        ),
    ),
    Mutant(
        "M88_AUDIT_DOES_NOT_NAME_THE_GOVERNING_VERSION",
        "apps/api/src/korpus/application/answer_audit.py",
        '                    "version_id": str(citation.version_id),',
        '                    "version_id": "",',
        (
            "apps/api/tests/test_audit_names_governing_version.py::test_the_event_names_the_version_and_span_the_answer_stood_on",
        ),
    ),
    Mutant(
        "M89_AUDIT_DROPS_THE_DATE_ANSWERED_FOR",
        "apps/api/src/korpus/application/answer_audit.py",
        '            "as_of": query.as_of.isoformat(),',
        '            "as_of": "",',
        (
            "apps/api/tests/test_audit_names_governing_version.py::test_the_event_records_the_date_the_answer_was_given_for",
        ),
    ),
    Mutant(
        "M90_CURRENCY_HAS_NO_LOWER_BOUND",
        "apps/api/src/korpus/domain/temporal.py",
        "    if start is None or start > as_of:",
        "    if start is not None and start > as_of:",
        (
            "apps/api/tests/test_currency_lower_bound.py::test_the_projection_ignores_an_unbounded_version_already_in_the_database",
        ),
    ),
    Mutant(
        "M91_PUBLICATION_DATE_NOT_A_LOWER_BOUND",
        "apps/api/src/korpus/domain/models.py",
        "        return self.effective_from or self.publication_date",
        "        return self.effective_from",
        (
            "apps/api/tests/test_currency_lower_bound.py::test_publication_date_serves_as_the_lower_bound_when_effective_from_is_absent",
        ),
    ),
    Mutant(
        "M92_APPROVAL_ACCEPTS_A_VERSION_THAT_GOVERNS_EVERY_PAST_DATE",
        "apps/api/src/korpus/application/ingestion.py",
        "        if transition.target is ReviewState.APPROVED and version.in_force_from is None:",
        "        if False:",
        (
            "apps/api/tests/test_currency_lower_bound.py::test_a_version_with_no_lower_bound_at_all_cannot_be_approved",
        ),
    ),
    Mutant(
        "M93_SQL_IGNORES_THE_LOWER_BOUND",
        "apps/api/src/korpus/infrastructure/retrieval_candidate_query.py",
        "              {compartment_clause}\n"
        "              AND COALESCE(v.effective_from, v.publication_date) <= :as_of",
        "              {compartment_clause}\n"
        "              AND COALESCE(v.effective_from, v.publication_date, :as_of) <= :as_of",
        (
            "apps/api/tests/test_currency_lower_bound.py::test_the_candidate_sql_excludes_an_unbounded_version",
        ),
    ),
    Mutant(
        "M94_SCHEMA_REVISION_PIN_UNCHECKED",
        "apps/api/src/korpus/infrastructure/schema.py",
        'SCHEMA_REVISION = "0022_approval_provenance_boundary"',
        'SCHEMA_REVISION = "0016_learning_course_graph"',
        (
            "apps/api/tests/test_schema_revision_pin.py::test_the_code_pins_the_head_of_the_migration_graph",
        ),
    ),
    Mutant(
        "M95_DELAYED_ANCHOR_REPORTED_AS_BROKEN_CHAIN",
        "apps/api/src/korpus/infrastructure/audit_reader.py",
        "        pending = head_sequence - anchor.sequence\n"
        "        return AuditVerification(\n"
        "            valid=True,",
        "        pending = head_sequence - anchor.sequence\n"
        "        return AuditVerification(\n"
        "            valid=pending == 0,",
        (
            "apps/api/tests/test_audit_anchor_semantics.py::test_an_anchor_behind_the_head_is_pending_not_invalid",
        ),
    ),
    Mutant(
        "M96_ANCHOR_AHEAD_OF_HEAD_ACCEPTED",
        "apps/api/src/korpus/infrastructure/audit_reader.py",
        "        if anchor.sequence > head_sequence:",
        "        if False:",
        (
            "apps/api/tests/test_audit_anchor_semantics.py::test_an_anchor_ahead_of_the_head_is_invalid",
        ),
    ),
    Mutant(
        "M97_ANCHOR_POSITION_HASH_NOT_COMPARED",
        "apps/api/src/korpus/infrastructure/audit_reader.py",
        "        if anchor.head_hash != anchor_at_position:",
        "        if False:",
        (
            "apps/api/tests/test_audit_anchor_semantics.py::test_an_anchor_that_disagrees_at_its_own_position_is_invalid",
        ),
    ),
    Mutant(
        "M98_SPAN_DISCLOSURE_BYPASSES_THE_RETRIEVAL_FILTER",
        "apps/api/src/korpus/api/routes_answers.py",
        "    rows = repository.get_retrievable_spans_by_ids(identity, identity.corpora, effective, [span_id])",
        '    rows = repository.get_retrievable_spans_by_ids(\n        identity.model_copy(\n            update={"clearance": 3, "corpora": frozenset({"public", "restricted-demo"})}\n        ),\n        frozenset({"public", "restricted-demo"}),\n        effective,\n        [span_id],\n    )',
        (
            "apps/api/tests/test_span_lookup.py::test_a_reader_cannot_open_a_span_they_could_not_have_been_cited",
        ),
    ),
    Mutant(
        "M99_SPAN_LISTING_IGNORES_THE_DATE",
        "apps/api/src/korpus/api/routes_answers.py",
        "    effective = as_of or datetime.now(UTC).date()\n    rows = repository.list_retrievable_spans(",
        "    effective = date(1900, 1, 1)\n    rows = repository.list_retrievable_spans(",
        (
            "apps/api/tests/test_span_lookup.py::test_a_span_is_not_disclosed_on_a_date_the_version_did_not_govern",
        ),
    ),
    Mutant(
        "M100_CITATION_SPAN_HASH_NOT_BOUND_TO_THE_SPAN",
        "apps/api/src/korpus/application/answer_query.py",
        "                    span_hash=item.span.text_hash,",
        '                    span_hash="",',
        (
            "apps/api/tests/test_span_lookup.py::test_the_answer_citation_resolves_to_a_span_that_contains_the_quote",
        ),
    ),
    Mutant(
        "M101_SECTION_NEVER_RECORDED",
        "apps/api/src/korpus/infrastructure/extraction.py",
        '                        "section": _section_at(markers, offset),',
        '                        "section": None,',
        ("apps/api/tests/test_span_lookup.py::test_a_span_carries_the_section_it_sits_under",),
    ),
    Mutant(
        "M102_SUPPORT_GATE_CANNOT_FAIL",
        "apps/api/src/korpus/application/answer_query.py",
        "            support_score = extractive_support(candidate.text, item.span.text)",
        "            support_score = 1.0",
        (
            "apps/api/tests/test_support_gate.py::test_the_extraction_step_drops_a_claim_below_the_support_threshold",
        ),
    ),
    Mutant(
        "M103_EMPTY_CLAIM_TRIVIALLY_SUPPORTED",
        "apps/api/src/korpus/application/evidence.py",
        "    if not tokens:\n        return 0.0",
        "    if not tokens:\n        return 1.0",
        ("apps/api/tests/test_support_gate.py::test_an_empty_claim_has_no_support",),
    ),
    Mutant(
        "M104_VERSION_NARROWING_DROPPED_FROM_SQL",
        "apps/api/src/korpus/infrastructure/repository.py",
        "        if version_id is not None:\n"
        "            statement = statement.where(versions.c.id == str(version_id))",
        "        if False:\n"
        "            statement = statement.where(versions.c.id == str(version_id))",
        (
            "apps/api/tests/test_span_lookup.py::"
            "test_listing_one_version_does_not_read_the_whole_corpus",
        ),
    ),
    Mutant(
        "M105_ANCHOR_DELIVERY_WALKS_ONE_ROW_PER_PASS",
        "apps/api/src/korpus/infrastructure/repository.py",
        "            .where(audit_anchor_outbox.c.sequence <= row.sequence)\n"
        "            .values(delivered_at=datetime.now(UTC))",
        "            .where(audit_anchor_outbox.c.sequence == row.sequence)\n"
        "            .values(delivered_at=datetime.now(UTC))",
        (
            "apps/api/tests/test_anchor_delivery_backlog.py::"
            "test_delivery_reports_how_many_checkpoints_it_closed",
        ),
    ),
    Mutant(
        "M106_SUPERSEDED_CHECKPOINTS_LEFT_PENDING",
        "apps/api/src/korpus/infrastructure/repository.py",
        "            .where(audit_anchor_outbox.c.sequence <= row.sequence)\n"
        "            .values(delivered_at=datetime.now(UTC))",
        "            .where(audit_anchor_outbox.c.sequence == row.sequence)\n"
        "            .values(delivered_at=datetime.now(UTC))",
        (
            "apps/api/tests/test_anchor_delivery_backlog.py::"
            "test_delivery_reports_how_many_checkpoints_it_closed",
        ),
    ),
    Mutant(
        "M107_GATE_INVENTORY_REPORTS_NOTHING",
        "apps/api/src/korpus/application/gate_inventory.py",
        '    outer = _dictionary_keys(OperationalReleaseGate.evaluate, "checks")',
        "    outer = ()",
        (
            "apps/api/tests/test_gate_negative_controls.py::"
            "test_every_gate_predicate_has_a_negative_control",
        ),
    ),
    Mutant(
        "M108_GATE_INVENTORY_MISSES_ASSURANCE_PREDICATES",
        "apps/api/src/korpus/application/gate_inventory.py",
        '    return _dictionary_keys(evaluate_assurance, "checks")',
        "    return ()",
        (
            "apps/api/tests/test_gate_negative_controls.py::"
            "test_every_assurance_predicate_has_a_negative_control",
        ),
    ),
    Mutant(
        "M109_EXTERNAL_GROUND_CLEARED_WITHOUT_ATTESTATION",
        "apps/api/src/korpus/application/admission.py",
        "        if kind in EXTERNAL_KINDS:\n"
        "            problems.extend(_attestation_problems(root, ground, registry))",
        "        if False:\n"
        "            problems.extend(_attestation_problems(root, ground, registry))",
        (
            "apps/api/tests/test_admission_register.py::"
            "test_an_external_ground_cannot_be_cleared_by_editing_the_register",
        ),
    ),
    Mutant(
        "M110_OPEN_GROUNDS_DO_NOT_WITHHOLD",
        "apps/api/src/korpus/application/admission.py",
        "    authorized = not open_grounds and not problems",
        "    authorized = not problems",
        (
            "apps/api/tests/test_admission_register.py::"
            "test_the_shipped_register_withholds_and_says_why",
        ),
    ),
    Mutant(
        "M111_CLEARED_GROUND_EVIDENCE_NOT_RESOLVED",
        "apps/api/src/korpus/application/admission.py",
        "            problems.extend(\n"
        '                f"{identifier}: {message}" '
        "for message in verify_references(root, evidence)\n"
        "            )",
        "            problems.extend(())",
        (
            "apps/api/tests/test_admission_register.py::"
            "test_a_ground_cleared_with_a_test_that_does_not_exist_is_refused",
        ),
    ),
    Mutant(
        "M112_GATE_AUTHORIZES_WITHOUT_A_REGISTER",
        "apps/api/src/korpus/application/operations.py",
        "            production_authorized=bool(\n"
        "                not failures and admission is not None "
        "and admission.production_authorized\n"
        "            ),",
        "            production_authorized=bool(not failures),",
        (
            "apps/api/tests/test_operations.py::"
            "test_operational_gate_passes_encoded_engineering_predicates_only",
        ),
    ),
    Mutant(
        "M113_FIXTURE_RUN_PRESENTS_ITSELF_AS_MEASURED",
        "apps/api/src/korpus/application/tevv.py",
        "    reasons = corpus_declaration_problems(corpus_declaration)",
        "    reasons: list[str] = []",
        (
            "apps/api/tests/test_tevv_admissibility.py::"
            "test_the_shipped_fixture_run_is_not_admissible",
        ),
    ),
    Mutant(
        "M114_SYNTHETIC_CORPUS_ACCEPTED_AS_REAL",
        "apps/api/src/korpus/application/tevv.py",
        '    if declaration.get("synthetic") is True:',
        "    if False:",
        (
            "apps/api/tests/test_tevv_admissibility.py::"
            "test_a_corpus_that_declares_itself_synthetic_is_refused",
        ),
    ),
    Mutant(
        "M115_UNCERTAINTY_REPORTED_AS_CERTAINTY",
        "apps/api/src/korpus/application/tevv.py",
        "    if interval.width > maximum_interval_width:",
        "    if False:",
        (
            "apps/api/tests/test_tevv_admissibility.py::"
            "test_a_wide_interval_is_refused_even_on_a_real_corpus",
        ),
    ),
    Mutant(
        "M116_RECOVERY_SCALE_CLAIM_TAKEN_ON_TRUST",
        "apps/api/src/korpus/application/recovery.py",
        (
            "        if rows < PRODUCTION_LIKE_MINIMUM_ROWS and "
            "plaintext < PRODUCTION_LIKE_MINIMUM_BYTES:"
        ),
        "        if False:",
        (
            "apps/api/tests/test_recovery_measurement.py::"
            "test_a_fixture_cannot_promote_itself_by_editing_a_string",
        ),
    ),
    Mutant(
        "M117_MISSING_RECOVERY_DRILL_READS_AS_EXECUTED",
        "apps/api/src/korpus/application/recovery.py",
        "        return self.status != MISSING",
        "        return True",
        ("apps/api/tests/test_recovery_measurement.py::test_no_report_is_not_a_pass",),
    ),
    Mutant(
        "M153_SWITCH_ALLOWED_ON_INCOMPLETE_INDEX",
        "apps/api/src/korpus/application/embedding_migration.py",
        "    if spans_embedded_target < spans_total:",
        "    if False:",
        ("apps/api/tests/test_embedding_migration.py::test_the_switch_requires_complete_coverage",),
    ),
    Mutant(
        "M154_RETIRE_ALLOWED_BEFORE_SWITCH",
        "apps/api/src/korpus/application/embedding_migration.py",
        "    if not switched:",
        "    if False:",
        ("apps/api/tests/test_embedding_migration.py::test_retiring_before_the_switch_is_refused",),
    ),
    Mutant(
        "M155_RESUME_SKIPS_A_GAP",
        "apps/api/src/korpus/application/embedding_migration.py",
        "        if batch.index not in done:",
        "        if batch.index < max(done, default=-1):",
        (
            "apps/api/tests/test_embedding_migration.py::"
            "test_resume_returns_the_first_gap_not_the_next_index",
        ),
    ),
    Mutant(
        "M150_UNKNOWN_QUERY_FAILS_OPEN",
        "apps/api/src/korpus/application/risk.py",
        "    if risk is QueryRisk.UNCLASSIFIED:",
        "    if False:",
        ("apps/api/tests/test_risk_rules.py::test_unclassified_costs_more_than_standard",),
    ),
    Mutant(
        "M151_UNRECOGNISED_QUERY_READS_AS_ORDINARY",
        "apps/api/src/korpus/application/risk_rules.py",
        "    return QueryRisk.UNCLASSIFIED, None",
        "    return QueryRisk.STANDARD, None",
        (
            "apps/api/tests/test_risk_rules.py::"
            "test_an_unrecognised_query_is_unclassified_not_standard",
        ),
    ),
    Mutant(
        "M152_REPHRASED_PERMISSION_QUESTION_SLIPS_THROUGH",
        "apps/api/src/korpus/application/risk_rules.py",
        '            r"\\b(чи можу|чи може|чи маю|чи повинен|чи потрібно|як діяти"',
        '            r"\\b(ZZ-nothing-matches-this|чи повинен|чи потрібно|як діяти"',
        (
            "apps/api/tests/test_risk_rules.py::"
            "test_a_rephrased_operational_question_is_still_operational",
        ),
    ),
    Mutant(
        "M149_IMAGE_MAY_BE_PINNED_BY_TAG_ALONE",
        "apps/api/src/korpus/infrastructure_requirements.py",
        '                    lambda c, n=name: (\n                        not c.service(n).get("image")\n                        or bool(DIGEST_PINNED.search(str(c.service(n)["image"])))\n                    ),',
        "                    lambda c, n=name: True,",
        ("apps/api/tests/test_image_pinning.py::test_a_tag_without_a_digest_is_refused",),
    ),
    Mutant(
        "M146_PLAINTEXT_SECRET_IN_TREE_UNDETECTED",
        "apps/api/src/korpus/repository_requirements.py",
        '        if (\n            relative.startswith("infra/secrets/")\n            and path.suffix == ".txt"\n            and relative in git_tracked\n        ):',
        "        if False:",
        (
            "apps/api/tests/test_repository_register.py::test_a_plaintext_secret_in_the_tree_is_detected",
        ),
    ),
    Mutant(
        # The fallback direction. Outside a repository nothing can tell an ignored
        # secret from a shipped one, so every secret file present must be a finding;
        # returning an empty set instead would make a packaged distribution report
        # clean over a credential it ships.
        "M170_UNTRACKABLE_SECRETS_ASSUMED_IGNORED",
        "apps/api/src/korpus/repository_requirements.py",
        "    git_tracked = tracked if tracked is not None else _EVERYTHING",
        "    git_tracked = tracked if tracked is not None else frozenset()",
        (
            "apps/api/tests/test_repository_register.py::"
            "test_a_plaintext_secret_in_the_tree_is_detected",
        ),
    ),
    Mutant(
        "M171_IGNORED_LOCAL_SECRET_REPORTED_AS_TRACKED",
        "apps/api/src/korpus/repository_requirements.py",
        "            and relative in git_tracked\n",
        "            and True\n",
        (
            "apps/api/tests/test_repository_register.py::test_a_secret_git_ignores_is_not_reported_as_tracked",
        ),
    ),
    Mutant(
        "M147_OVERSIZED_FILE_UNDETECTED",
        "apps/api/src/korpus/repository_requirements.py",
        "        if _is_oversized_file(context, path, relative):",
        "        if False:",
        ("apps/api/tests/test_repository_register.py::test_an_oversized_file_is_detected",),
    ),
    Mutant(
        "M148_UNRESOLVED_PLACEHOLDER_UNDETECTED",
        "apps/api/src/korpus/repository_requirements.py",
        "            if any(pattern.search(text) for pattern in PLACEHOLDER_PATTERNS):",
        "            if False:",
        ("apps/api/tests/test_repository_register.py::test_an_unresolved_placeholder_is_detected",),
    ),
    Mutant(
        "M143_REQUIREMENTS_STOP_AT_THE_FIRST_FAILURE",
        "apps/api/src/korpus/application/requirements.py",
        "    unmet = tuple(requirement for requirement in listed "
        "if not requirement.evaluate(context))",
        "    unmet = tuple(listed[:1]) if listed and not listed[0].evaluate(context) else ()",
        (
            "apps/api/tests/test_requirement_registry.py::"
            "test_all_requirements_are_evaluated_not_just_up_to_the_first_failure",
        ),
    ),
    Mutant(
        "M144_A_BROKEN_PREDICATE_COUNTS_AS_SATISFIED",
        "apps/api/src/korpus/application/requirements.py",
        "        except Exception:  # noqa: BLE001 - the predicate's own failure is the answer\n"
        "            return False",
        "        except Exception:  # noqa: BLE001 - the predicate's own failure is the answer\n"
        "            return True",
        (
            "apps/api/tests/test_requirement_registry.py::"
            "test_a_predicate_that_raises_fails_its_own_requirement",
        ),
    ),
    Mutant(
        "M145_DUPLICATE_REQUIREMENT_IDS_UNDETECTED",
        "apps/api/src/korpus/application/requirements.py",
        "    return sorted(identifier for identifier, count in seen.items() if count > 1)",
        "    return []",
        ("apps/api/tests/test_requirement_registry.py::test_duplicate_ids_are_actually_detected",),
    ),
    Mutant(
        "M139_UNSIGNED_ATTESTATION_ACCEPTED",
        "apps/api/src/korpus/security/attestors.py",
        "        if not key_id or not signature_b64:",
        "        if False:",
        ("apps/api/tests/test_attestation_signatures.py::test_an_unsigned_attestation_is_refused",),
    ),
    Mutant(
        "M140_ANY_ENROLLED_KEY_MAY_ATTEST_ANY_GROUND",
        "apps/api/src/korpus/security/attestors.py",
        "        if key.role not in entitled:",
        "        if False:",
        (
            "apps/api/tests/test_attestation_signatures.py::"
            "test_a_corpus_owner_cannot_sign_the_independent_assessment",
        ),
    ),
    Mutant(
        "M141_SIGNATURE_NOT_BOUND_TO_THE_GROUND",
        "apps/api/src/korpus/security/attestors.py",
        '                "ground_id": ground_id,',
        '                "ground_id": "any",',
        (
            "apps/api/tests/test_attestation_signatures.py::"
            "test_a_signature_obtained_for_another_ground_cannot_be_moved",
        ),
    ),
    Mutant(
        "M142_MISSING_ATTESTOR_REGISTRY_CLEARS_GROUNDS",
        "apps/api/src/korpus/application/admission.py",
        "    if registry is not None:",
        "    if False:",
        (
            "apps/api/tests/test_attestation_signatures.py::"
            "test_the_admission_verdict_refuses_a_clearance_with_no_signature",
        ),
    ),
    Mutant(
        "M135_ATTESTED_DOCUMENT_NEED_NOT_EXIST",
        "apps/api/src/korpus/application/admission.py",
        "    if not resolved.is_file():",
        "    if False:",
        (
            "apps/api/tests/test_admission_cannot_be_self_granted.py::"
            "test_an_attestation_naming_a_document_that_does_not_exist_is_refused",
        ),
    ),
    Mutant(
        "M136_ATTESTATION_DIGEST_NOT_CHECKED",
        "apps/api/src/korpus/application/admission.py",
        "    elif hashlib.sha256(resolved.read_bytes()).hexdigest() != digest:",
        "    elif False:",
        (
            "apps/api/tests/test_admission_cannot_be_self_granted.py::"
            "test_an_attestation_whose_digest_does_not_match_the_document_is_refused",
        ),
    ),
    Mutant(
        "M137_ASSESSMENT_MAY_BE_SELF_SIGNED",
        "apps/api/src/korpus/application/admission.py",
        '    if ground.get("kind") == "external_assessment":',
        "    if False:",
        (
            "apps/api/tests/test_admission_cannot_be_self_granted.py::"
            "test_an_independent_assessment_signed_by_the_engineering_owner_is_refused",
        ),
    ),
    Mutant(
        "M138_ATTESTATION_MAY_BE_DATED_IN_THE_FUTURE",
        "apps/api/src/korpus/application/admission.py",
        "        if signed > date.today():",
        "        if False:",
        (
            "apps/api/tests/test_admission_cannot_be_self_granted.py::"
            "test_an_attestation_signed_in_the_future_is_refused",
        ),
    ),
    Mutant(
        "M132_RAGGED_TABLE_READS_AS_INTACT",
        "apps/api/src/korpus/application/table_integrity.py",
        "        if len(widths) > 1:",
        "        if False:",
        ("apps/api/tests/test_table_integrity.py::test_a_row_that_lost_a_column_is_flagged",),
    ),
    Mutant(
        "M133_TABLE_DAMAGE_NEVER_REACHES_REVIEW",
        "apps/api/src/korpus/application/extraction_quality.py",
        "    flags.update(assess_table_integrity(text).flags)",
        "    pass",
        (
            "apps/api/tests/test_table_integrity.py::"
            "test_table_damage_reaches_the_reviewer_through_the_extraction_quality_gate",
        ),
    ),
    Mutant(
        "M134_PROSE_FLAGGED_AS_A_BROKEN_TABLE",
        "apps/api/src/korpus/application/table_integrity.py",
        'COLUMN_GAP = re.compile(r"(?: {2,}|\\t+)")',
        'COLUMN_GAP = re.compile(r"(?: +|\\t+)")',
        (
            "apps/api/tests/test_table_integrity.py::"
            "test_wrapped_prose_with_single_spaces_is_not_a_table",
        ),
    ),
    Mutant(
        "M127_SPLIT_NUMBER_NOT_FLAGGED",
        "apps/api/src/korpus/application/numeric_integrity.py",
        "    for match in SPLIT_NUMBER.finditer(text):",
        "    for match in []:",
        ("apps/api/tests/test_numeric_integrity.py::test_a_number_split_by_a_space_is_flagged",),
    ),
    Mutant(
        "M128_NUMERIC_DAMAGE_NEVER_REACHES_REVIEW",
        "apps/api/src/korpus/application/extraction_quality.py",
        "    flags.update(assess_numeric_integrity(text).flags)",
        "    pass",
        (
            "apps/api/tests/test_numeric_integrity.py::"
            "test_numeric_damage_reaches_the_reviewer_through_the_extraction_quality_gate",
        ),
    ),
    Mutant(
        "M129_EMPTY_INDEX_REPORTS_FULL_COVERAGE",
        "apps/api/src/korpus/application/embedding_coverage.py",
        "        if self.spans_total == 0:\n            return 0.0",
        "        if self.spans_total == 0:\n            return 1.0",
        (
            "apps/api/tests/test_embedding_coverage.py::"
            "test_an_empty_corpus_covers_nothing_rather_than_everything",
        ),
    ),
    Mutant(
        "M130_STALE_VECTORS_RANKED_BELOW_MISSING",
        "apps/api/src/korpus/application/embedding_coverage.py",
        "    elif spans_stale_text > 0:",
        "    elif False:",
        ("apps/api/tests/test_embedding_coverage.py::test_a_stale_vector_outranks_a_missing_one",),
    ),
    Mutant(
        "M131_REQUIRED_SEMANTIC_MODE_FALLS_BACK_SILENTLY",
        "apps/api/src/korpus/application/embedding_coverage.py",
        "    if coverage.complete:",
        "    if True:",
        (
            "apps/api/tests/test_embedding_coverage.py::"
            "test_required_semantic_mode_refuses_an_incomplete_index",
        ),
    ),
    Mutant(
        "M124_EXPORT_SHIPS_A_SEQUENCE_GAP",
        "apps/api/src/korpus/application/audit_export.py",
        "        if current.sequence != previous.sequence + 1:",
        "        if False:",
        ("apps/api/tests/test_audit_export.py::test_a_sequence_gap_inside_the_batch_is_refused",),
    ),
    Mutant(
        "M125_EXPORT_SHIPS_A_BROKEN_CHAIN_LINK",
        "apps/api/src/korpus/application/audit_export.py",
        "        if current.previous_hash != previous.event_hash:",
        "        if False:",
        (
            "apps/api/tests/test_audit_export.py::"
            "test_a_broken_link_is_refused_even_when_the_sequences_are_consecutive",
        ),
    ),
    Mutant(
        "M126_EXPORT_LEAKS_PAYLOADS_BY_DEFAULT",
        "apps/api/src/korpus/application/audit_export.py",
        "                payload=json.loads(canonical) if include_payload else None,",
        "                payload=json.loads(canonical),",
        ("apps/api/tests/test_audit_export.py::test_payloads_are_excluded_unless_asked_for",),
    ),
    Mutant(
        "M121_LEGAL_HOLD_DOES_NOT_OUTRANK_THE_TIMER",
        "apps/api/src/korpus/application/retention.py",
        "        if policy.legal_hold:",
        "        if False:",
        (
            "apps/api/tests/test_retention_planning.py::"
            "test_legal_hold_outranks_the_retention_period",
        ),
    ),
    Mutant(
        "M122_EXPIRED_MATERIAL_DELETED_WITHOUT_PERMISSION",
        "apps/api/src/korpus/application/retention.py",
        "        elif CorpusOperation.DELETE in policy.allowed_operations:",
        "        elif True:",
        (
            "apps/api/tests/test_retention_planning.py::"
            "test_a_document_past_its_period_without_delete_permission_awaits_a_decision",
        ),
    ),
    Mutant(
        "M123_UNGOVERNED_CORPUS_TREATED_AS_GOVERNED",
        "apps/api/src/korpus/application/retention.py",
        "        if policy is None:",
        "        if False:",
        (
            "apps/api/tests/test_retention_planning.py::"
            "test_a_corpus_with_no_policy_is_ungoverned_rather_than_assumed_safe",
        ),
    ),
    Mutant(
        "M119_REVIEW_TRANSITION_SKIPS_ENTITLEMENT",
        "apps/api/src/korpus/application/ingestion.py",
        "        if not self.policy.can_access_document(actor, document).allowed:\n"
        '            raise PermissionError("actor cannot access target document")\n'
        "        permission = (",
        "        permission = (",
        (
            "apps/api/tests/test_repository_access_refusals.py::"
            "test_a_reviewer_cannot_transition_a_version_from_another_corpus",
        ),
    ),
    Mutant(
        "M120_QUEUED_VERSION_SKIPS_ENTITLEMENT",
        "apps/api/src/korpus/application/ingestion_jobs.py",
        "        if not self.policy.can_access_document(actor, document).allowed:\n"
        '            raise PermissionError("actor cannot access target document")\n'
        "        key = self.quarantine_store.put_path(path, source_hash, filename)",
        "        key = self.quarantine_store.put_path(path, source_hash, filename)",
        (
            "apps/api/tests/test_repository_access_refusals.py::"
            "test_a_version_cannot_be_queued_against_a_document_in_another_corpus",
        ),
    ),
    Mutant(
        "M118_RECOVERY_PROVENANCE_NOT_REQUIRED",
        "apps/api/src/korpus/application/recovery.py",
        (
            "    absent = [field for field in REQUIRED_PROVENANCE "
            'if provenance.get(field) in (None, "")]'
        ),
        "    absent = []",
        (
            "apps/api/tests/test_recovery_measurement.py::"
            "test_a_duration_without_provenance_is_not_a_measurement",
        ),
    ),
    # OPS-004. Every one of these turns a finding into a silence, which is the only
    # way a drift checker fails without anyone noticing: it keeps reporting IN_SYNC.
    Mutant(
        # The binding between an answer's text and its citations is decided once. A
        # mutable Answer lets anything downstream change the sentence while keeping the
        # citations that justified a different one.
        "M178_ANSWER_EDITABLE_AFTER_THE_POLICY_DECIDED_IT",
        "apps/api/src/korpus/domain/models.py",
        "    model_config = ConfigDict(frozen=True)\n\n"
        "    id: UUID = Field(default_factory=uuid4)\n    status: AnswerStatus",
        "    id: UUID = Field(default_factory=uuid4)\n    status: AnswerStatus",
        (
            "apps/api/tests/test_architecture.py::"
            "test_the_answer_cannot_be_edited_after_the_policy_decided_it",
        ),
    ),
    Mutant(
        # `source_hash: str = Field(pattern=...)` appears three times in this file —
        # DocumentVersionRecord, Citation and IngestionJobRecord — so the bare line
        # mutates all three, and the mutant is then answered by whichever test happens
        # to cover any of them. Anchored on the line above it, which is Citation's
        # alone. Two occurrences under one mutant is not two covered call sites: that
        # is exactly how M05 passed for months.
        "M179_CITATION_SOURCE_HASH_UNCONSTRAINED",
        "apps/api/src/korpus/domain/models.py",
        "#: system says it did, which is the one place the shape has to be certain.\n"
        '    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")',
        "#: system says it did, which is the one place the shape has to be certain.\n"
        "    source_hash: str",
        (
            "apps/api/tests/test_architecture.py::"
            "test_the_citation_hash_has_the_same_shape_as_the_version_it_points_at",
        ),
    ),
    Mutant(
        # A DOCX is a ZIP. Without the signature check a renamed archive picks its own
        # reader, which is the whole point of validating extension against bytes.
        "M189_RENAMED_ARCHIVE_REACHES_THE_DOCX_PARSER",
        "apps/api/src/korpus/infrastructure/extraction.py",
        '        if not prefix.startswith(b"PK\\x03\\x04"):',
        "        if False:",
        (
            "apps/api/tests/test_extraction.py::"
            "test_a_zip_renamed_to_docx_is_refused_before_the_parser",
        ),
    ),
    Mutant(
        # `xml.etree` expands internal entities. A bounded expansion can be miscounted;
        # a refused declaration cannot.
        "M190_DOCX_ENTITY_DECLARATION_ACCEPTED",
        "apps/api/src/korpus/infrastructure/extraction.py",
        '    if b"<!doctype" in head or b"<!entity" in head:',
        "    if False:",
        ("apps/api/tests/test_extraction.py::test_a_docx_declaring_an_entity_is_refused",),
    ),
    Mutant(
        # The gap `table_integrity` looks for was erased before it could see it, so the
        # module that exists against "a number quoted under another column's heading"
        # could not fire on any real document.
        "M191_NORMALISATION_ERASES_THE_COLUMN_GAP",
        "apps/api/src/korpus/infrastructure/extraction.py",
        '    text = re.sub(r"(?<! ) {2}(?! )", " ", text)',
        '    text = re.sub(r"[ \\t]+", " ", text)',
        (
            "apps/api/tests/test_extraction.py::"
            "test_normalisation_keeps_the_column_gap_a_flattened_table_leaves",
        ),
    ),
    Mutant(
        # The sandbox runs in the *document's* directory. A relative PYTHONPATH — which
        # is what the Makefile and every shell line carry — then resolves against that
        # directory and finds nothing, and the whole batch reports itself as four hundred
        # malformed documents rather than one wrong variable.
        "M192_PARSER_SANDBOX_PATH_LEFT_RELATIVE",
        "apps/api/src/korpus/infrastructure/extraction.py",
        """        "PYTHONPATH": os.pathsep.join(
            str(Path(entry).resolve())
            for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep)
            if entry
        ),""",
        """        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),""",
        (
            "apps/api/tests/test_parser_sandbox_path.py::"
            "test_a_relative_pythonpath_is_resolved_before_the_worker_sees_it",
        ),
    ),
    Mutant(
        "M193_UNDATED_SOURCE_PASSES_UNANNOUNCED",
        "apps/api/src/korpus/application/answer_analysis.py",
        "    cited_undated = sum(1 for citation in citations if citation.version_id in undated)",
        "    cited_undated = 0",
        (
            "apps/api/tests/test_undated_source_limitation.py::test_a_citation_without_a_publication_date_says_so",
        ),
    ),
    Mutant(
        # pypdf walks the page tree lazily, so `PdfReader(strict=True)` succeeding says
        # nothing about it. Unguarded, the walk raised out of this module's vocabulary
        # and ended a 1740-document import at 918.
        "M194_PAGE_TREE_WALK_LEFT_UNGUARDED",
        "apps/api/src/korpus/infrastructure/pdf_extraction.py",
        "    except (KeyError, ValueError, TypeError, RecursionError, PdfReadError) as exc:\n"
        '        raise ValueError("malformed PDF page tree") from exc',
        "    except RecursionError as exc:\n"
        '        raise ValueError("malformed PDF page tree") from exc',
        (
            "apps/api/tests/test_malformed_pdf_containment.py::"
            "test_a_page_tree_that_fails_when_walked_leaves_as_a_named_refusal",
        ),
    ),
    Mutant(
        # `ORDER BY bm25` pushes every full-text match through the supersession test.
        # Correlated, that was 23 626 evaluations for a five-token question on a real
        # corpus — 2.5 s against a 1200 ms budget — and the deadline breach reached the
        # reader as "the corpus holds nothing".
        "M195_SUPERSESSION_TEST_CORRELATED_AGAIN",
        "apps/api/src/korpus/infrastructure/retrieval_candidate_query.py",
        "              AND (v.id, v.document_id) NOT IN (SELECT id, document_id FROM superseded)\n"
        "            ORDER BY bm25(evidence_fts), s.id",
        "              AND NOT EXISTS (\n"
        "                SELECT 1 FROM document_versions sv\n"
        "                WHERE sv.supersedes_version_id = v.id\n"
        "                  AND sv.review_state = 'approved'\n"
        "              )\n"
        "            ORDER BY bm25(evidence_fts), s.id",
        (
            "apps/api/tests/test_retrieval_supersession_cost.py::"
            "test_the_supersession_test_is_not_evaluated_per_matching_span",
        ),
    ),
    Mutant(
        # The old path got currency for free: it built a version model per span and
        # called `is_valid_on`. Computing the digest from a projection means asking the
        # same question explicitly, and dropping it puts tomorrow's order into today's
        # fingerprint — every answer stamped with a corpus it was not drawn from.
        "M196_RELEASE_ID_IGNORES_CURRENCY",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        (
            "            visible = [row for row in rows "
            "if retrieval_queries.release_row_is_current(row, as_of)]"
        ),
        "            visible = list(rows)",
        (
            "apps/api/tests/test_corpus_release_identity.py::"
            "test_a_version_not_yet_in_force_is_not_in_the_release",
        ),
    ),
    Mutant(
        # The one thing a language model must never do here. Searching only what it
        # suggested lets a planner steer a reader away from the passage they asked for,
        # and nothing downstream can see that it happened.
        "M197_PLANNER_REPLACES_THE_QUESTION",
        "apps/api/src/korpus/application/query_plan.py",
        "        return (self.asked, *self.variants)",
        "        return self.variants or (self.asked,)",
        (
            "apps/api/tests/test_query_planner_boundary.py::"
            "test_the_question_asked_is_always_the_first_search",
        ),
    ),
    Mutant(
        # Admission is what stops a suggestion from being a sentence. Without it the
        # audit record carries assertions the system is made to look like it weighed.
        "M198_PLANNER_SUGGESTION_ADMITTED_UNCHECKED",
        "apps/api/src/korpus/application/query_plan.py",
        "        admitted = admissible_variant(candidate, question)",
        "        admitted = str(candidate)",
        (
            "apps/api/tests/test_query_planner_boundary.py::"
            "test_a_planner_that_returns_prose_contributes_nothing",
        ),
    ),
    Mutant(
        # A user password means the document is a secret. Accepting an unopenable file
        # would put an empty or garbled version into the corpus under a real title.
        "M199_ENCRYPTED_PDF_ACCEPTED_WITHOUT_OPENING",
        "apps/api/src/korpus/infrastructure/pdf_extraction.py",
        (
            "        if not opened:\n"
            '            raise ValueError("encrypted PDF requires '
            'a password that was not supplied")'
        ),
        (
            "        if False:\n"
            '            raise ValueError("encrypted PDF requires '
            'a password that was not supplied")'
        ),
        (
            "apps/api/tests/test_owner_restricted_pdf.py::"
            "test_a_document_with_a_user_password_is_still_refused",
        ),
    ),
    Mutant(
        # `cp` on a WAL database captures a torn page set and leaves the -wal behind, and
        # the copy opens without complaint. A backup that restores cleanly and wrong is
        # the failure this whole drill exists against.
        "M200_BACKUP_SNAPSHOT_IS_A_FILE_COPY",
        "scripts/backup_sqlite.sh",
        '    connection.execute("VACUUM INTO ?", (target,))',
        "    open(target, 'wb').write(open(source, 'rb').read(4096))",
        (
            "apps/api/tests/test_corpus_backup_drill.py::"
            "test_a_backup_restores_to_a_corpus_that_can_be_cited",
        ),
    ),
    Mutant(
        # Raising a source's authority class is the smallest edit that changes what the
        # system will say, and it is invisible in a file nobody signed.
        "M201_RELEASE_MANIFEST_SIGNATURE_NOT_CHECKED",
        "scripts/corpus_release.py",
        "    intact = hmac.compare_digest(recorded, _sign(manifest, key))",
        "    intact = True",
        (
            "apps/api/tests/test_corpus_release_manifest.py::"
            "test_raising_an_authority_class_breaks_the_signature",
        ),
    ),
    Mutant(
        # After a restore the question is which corpus this is. A comparison that always
        # agrees answers "the one you expected" whatever was restored.
        "M202_RELEASE_MATCHES_ANY_DATABASE",
        "scripts/corpus_release.py",
        (
            '        result["matches_database"] = current["content_digest"] '
            '== manifest.get("content_digest")'
        ),
        '        result["matches_database"] = True',
        (
            "apps/api/tests/test_corpus_release_manifest.py::"
            "test_a_different_corpus_is_reported_as_a_different_release",
        ),
    ),
    Mutant(
        # An event that does not say which key signed it cannot be verified after the
        # first rotation, and an unverifiable event in an append-only chain is
        # indistinguishable from a forged one.
        "M203_AUDIT_EVENT_VERIFIED_WITH_THE_WRONG_KEY",
        "apps/api/src/korpus/infrastructure/audit_reader.py",
        '            signed_by = str(row["audit_key_id"] or LEGACY_KEY_ID)',
        "            signed_by = self.audit_keyring.active_key_id",
        (
            "apps/api/tests/test_audit_key_rotation.py::"
            "test_the_chain_written_under_one_key_verifies_after_rotating_to_another",
        ),
    ),
    Mutant(
        # A verifier that ignores what it cannot check reports a chain as intact while
        # its middle is unreadable.
        "M204_UNKNOWN_SIGNING_KEY_TREATED_AS_VALID",
        "apps/api/src/korpus/application/keyring.py",
        "        material = self.keys.get(key_id or LEGACY_KEY_ID)\n"
        "        if material is None:\n"
        "            return False",
        "        material = self.keys.get(key_id or LEGACY_KEY_ID)\n"
        "        if material is None:\n"
        "            return True",
        (
            "apps/api/tests/test_audit_key_rotation.py::"
            "test_an_event_naming_an_unknown_key_is_invalid",
        ),
    ),
    Mutant(
        # "не менше 30 м" and "не менше 300 м" differ by one character. A gate that only
        # checked that every token appears somewhere in the evidence would pass both.
        "M205_COMPOSED_OPENING_MAY_STATE_A_NUMBER",
        "apps/api/src/korpus/application/composition.py",
        "    if _NUMBER.search(text):",
        "    if False:",
        (
            "apps/api/tests/test_answer_composition.py::"
            "test_an_opening_that_states_a_number_is_refused",
        ),
    ),
    Mutant(
        # One word flips a norm without changing its vocabulary, and "не" appears in
        # almost every Ukrainian document — so token presence cannot catch it.
        "M206_COMPOSED_OPENING_MAY_NEGATE",
        "apps/api/src/korpus/application/composition.py",
        "        if token in _NEGATION:\n"
        '            raise CompositionRefused(f"opening introduces a negation: {token!r}")',
        "        if False:\n"
        '            raise CompositionRefused(f"opening introduces a negation: {token!r}")',
        (
            "apps/api/tests/test_answer_composition.py::"
            "test_an_opening_that_introduces_a_negation_is_refused",
        ),
    ),
    Mutant(
        # The one rule that keeps a composition a rearrangement rather than a claim.
        "M207_COMPOSED_OPENING_MAY_ADD_A_WORD",
        "apps/api/src/korpus/application/composition.py",
        "        if missing:\n"
        "            raise CompositionRefused(\n"
        '                f"opening states something the evidence does not: {missing[0]!r}"\n'
        "            )",
        "        if False:\n"
        "            raise CompositionRefused(\n"
        '                f"opening states something the evidence does not: {missing[0]!r}"\n'
        "            )",
        (
            "apps/api/tests/test_answer_composition.py::"
            "test_an_opening_that_states_something_the_evidence_does_not_is_refused",
        ),
    ),
    Mutant(
        # Кожен токен «десь у доказах» — твердження про словник, а не про джерело. Дві
        # правдиві цитати дають третє речення, якого не каже жодна. Виміряно 31.08.2026.
        "M343_COMPOSED_OPENING_MAY_POOL_CITATIONS",
        "apps/api/src/korpus/application/composition.py",
        "        if content and not any(set(content) <= vocabulary for vocabulary in vocabularies):",
        "        if False:",
        (
            "apps/api/tests/test_answer_composition.py::"
            "test_an_opening_that_borrows_words_from_two_citations_is_refused",
        ),
    ),
    Mutant(
        # «КП», «БК», «ЗС» — рівно та форма, яку правило «менш ніж три літери» пропускало.
        "M344_COMPOSED_OPENING_MAY_SKIP_SHORT_TOKENS",
        "apps/api/src/korpus/application/composition.py",
        "    return [token for token in _tokens(text) if token not in _FUNCTION_WORDS]",
        "    return [\n"
        "        token\n"
        "        for token in _tokens(text)\n"
        "        if token not in _FUNCTION_WORDS and len(token) >= 3\n"
        "    ]",
        (
            "apps/api/tests/test_answer_composition.py::"
            "test_a_short_abbreviation_the_evidence_does_not_carry_is_refused",
        ),
    ),
    Mutant(
        # Перестановка звіряється через casefold, тож рядки МОДЕЛІ доходили до читача
        # замість спанів, які несуть хеші.
        "M345_READER_MAY_SEE_COMPOSER_STRINGS",
        "apps/api/src/korpus/application/composition.py",
        "        arranged = _retrieved_in_composed_order(sentences, ordered)",
        "        arranged = tuple(ordered)",
        (
            "apps/api/tests/test_answer_composition.py::"
            "test_the_reader_is_shown_the_retrieved_span_not_the_composer_string",
        ),
    ),
    Mutant(
        # Покриття питання каже, скільки слів збіглося, і мовчить про те, чи вціліла
        # думка. Знявши цей ключ, уривок із вищим покриттям знову стає головним доказом.
        "M346_FRAGMENT_MAY_OUTRANK_A_WHOLE_SENTENCE",
        "apps/api/src/korpus/application/answer_query.py",
        "                    starts_mid_sentence(candidate.text),\n",
        "                    False,\n",
        (
            "apps/api/tests/test_citation_fragments.py::"
            "test_a_whole_sentence_outranks_a_fragment_that_matches_more_of_the_question",
        ),
    ),
    Mutant(
        # Коли показати можна лише уривок, читач мусить це побачити. Константа False
        # лишає відповідь такою самою на вигляд і знімає єдине попередження.
        "M347_FRAGMENT_HIDDEN_FROM_THE_READER",
        "apps/api/src/korpus/application/answer_query.py",
        "                    quote_starts_mid_sentence=starts_mid_sentence(candidate.text),",
        "                    quote_starts_mid_sentence=False,",
        (
            "apps/api/tests/test_citation_fragments.py::"
            "test_when_only_a_fragment_can_be_shown_the_reader_is_told",
        ),
    ),
    Mutant(
        # Поріг, повернений до чверті питання, знову впускає 17 чужих питань із 20 під
        # зелений вирок. Значення живе в одному місці, тож і мутант один.
        "M348_QUERY_COVERAGE_BACK_TO_A_QUARTER",
        "apps/api/src/korpus/config.py",
        "    min_query_coverage: float = Field(0.5, ge=0, le=1)",
        "    min_query_coverage: float = Field(0.25, ge=0, le=1)",
        (
            "apps/api/tests/test_query_coverage_threshold.py::"
            "test_the_shipped_threshold_is_half_the_question",
        ),
    ),
    Mutant(
        # Єдина вісь, що вміє спіймати підміну предмета при високому покритті. Без неї
        # питання про ЦИВІЛЬНІ обʼєкти знову отримує норму про ВОЄННІ під зеленим вироком.
        "M349_SUBJECT_SUBSTITUTION_AXIS_DISABLED",
        "apps/api/src/korpus/application/answer_adjudication.py",
        "        if asked.search(question) and not asked.search(quote) and opposite.search(quote):",
        "        if False:",
        (
            "apps/api/tests/test_answer_adjudication.py::"
            "test_a_quote_about_the_opposite_category_is_contested",
        ),
    ),
    Mutant(
        # Поріг на ЧАСТКУ відрізняє колонку від речення, у якому PDF лишив прогалину.
        # Нуль повертає правило на ФАКТ прогону — і воно знову відхиляє нормальну прозу.
        "M350_LAYOUT_RULE_BACK_TO_ANY_GAP",
        "apps/api/src/korpus/application/answer_adjudication.py",
        "_LAYOUT_SHARE = 0.25",
        "_LAYOUT_SHARE = 0.0",
        (
            "apps/api/tests/test_answer_adjudication.py::"
            "test_prose_with_one_wide_gap_is_not_a_column",
        ),
    ),
    Mutant(
        # Голос осі, що відхилила, важить більше за згоду решти: саме одна вісь і давала
        # «ПІДСТАВА Є» рядку про позивний «Буг».
        "M351_DISSENTING_AXIS_OUTVOTED",
        "apps/api/src/korpus/application/answer_adjudication.py",
        '    if any(item.verdict == "DOES_NOT_SUPPORT" for item in verdicts):',
        "    if False:",
        (
            "apps/api/tests/test_answer_adjudication.py::"
            "test_one_dissenting_axis_outweighs_the_agreement_of_the_rest",
        ),
    ),
    Mutant(
        # Осі, що міркують про питання, мусять мовчати на мішку ключових слів — інакше
        # вони міряють власну вигадку.
        "M352_SUBJECT_AXIS_JUDGES_A_KEYWORD_BAG",
        "apps/api/src/korpus/application/answer_adjudication.py",
        "    if not is_question(question):\n"
        '        return AxisVerdict("contrast", "CANNOT_ADJUDICATE", "на вході не питання")',
        "    if False:\n"
        '        return AxisVerdict("contrast", "CANNOT_ADJUDICATE", "на вході не питання")',
        (
            "apps/api/tests/test_answer_adjudication.py::"
            "test_the_axis_that_can_reject_does_not_judge_a_keyword_bag",
        ),
    ),
    Mutant(
        # Коли ВСЯ показана підстава спірна, відповідь мусить піти до людини, а не бути
        # виданою з позначкою, якої читач може не помітити.
        "M353_CONTESTED_ANSWER_STILL_SHIPS",
        "apps/api/src/korpus/application/answer_query.py",
        '        if citations and all(citation.presentation == "contested" for citation in citations):',
        "        if False:",
        (
            "apps/api/tests/test_answer_adjudication.py::"
            "test_when_every_citation_is_contested_the_answer_goes_to_a_human",
        ),
    ),
    Mutant(
        # Гейт, що не помічає ЗНИКЛОГО мутанта, — це той самий стан, у якому звіт на 379
        # лежав поруч із каталогом на 385 і читався як доказ.
        "M354_FRESHNESS_GATE_IGNORES_A_MISSING_MUTANT",
        "scripts/check_mutation_report_freshness.py",
        "    missing = sorted(expected - reported)",
        "    missing = []",
        (
            "apps/api/tests/test_mutation_report_freshness.py::"
            "test_a_mutant_the_report_never_saw_is_caught",
        ),
    ),
    Mutant(
        # Стеля на чужих питаннях — єдина вісь, що ловить повернення до стану «17 із 20
        # чужих питань під зеленим вироком». Знявши її, ратчет лишається однобоким і
        # приймає систему, яка відповідає на все.
        "M355_QUALITY_RATCHET_IGNORES_FOREIGN_QUESTIONS",
        "scripts/check_answer_quality_ratchet.py",
        "    if outside > ceiling:",
        "    if False:",
        (
            "apps/api/tests/test_answer_quality_ratchet.py::"
            "test_letting_in_more_foreign_questions_is_caught",
        ),
    ),
    Mutant(
        # Ланка, яка тримала «нуль зі ста одного»: пересортування за сирою оцінкою
        # скасовувало ранжування, побудоване diversify_evidence, і документ, який Й Є
        # відповіддю, їхав у хвіст саме тому, що не повторює слів питання.
        "M356_PLAN_SEARCH_RESORTS_BY_RAW_SCORE",
        "apps/api/src/korpus/application/pec_retrieval.py",
        "    return [best[key] for key in order]",
        "    return sorted(best.values(), key=lambda item: -item.score)",
        (
            "apps/api/tests/test_declared_subject_admission.py::"
            "test_the_plan_search_keeps_the_order_the_ranker_built",
        ),
    ),
    Mutant(
        # Допуск за оголошеним предметом. Без нього стаття з найнижчою сирою оцінкою
        # (0.181 проти порога 0.25) викидається тим самим порогом, чию сліпоту вона
        # й ілюструє.
        "M357_ADMISSION_IGNORES_THE_DECLARED_SUBJECT",
        "apps/api/src/korpus/application/evidence_admission.py",
        "    if declares_the_subject:\n        return True",
        "    if False:\n        return True",
        (
            "apps/api/tests/test_subject_admission_floor.py::"
            "test_a_declared_subject_passes_a_floor_its_wording_cannot_clear",
        ),
    ),
    Mutant(
        # Лексична вісь мусить УТРИМАТИСЬ там, де вона структурно сліпа. Заперечення
        # звідти позначає спірною кожну статтю, яка й є відповіддю.
        "M358_BLIND_AXIS_CONTESTS_INSTEAD_OF_ABSTAINING",
        "apps/api/src/korpus/application/answer_adjudication.py",
        "    if subject_declared:",
        "    if False:",
        (
            "apps/api/tests/test_declared_subject_admission.py::"
            "test_the_lexical_axis_abstains_where_it_is_structurally_blind",
        ),
    ),
    Mutant(
        # Вердикт = найслабша вісь. Середнє ховає рівно те, заради чого профіль існує:
        # одна провалена вісь при п'ятьох відмінних дає «добре».
        "M361_VERDICT_TAKES_THE_MEAN_INSTEAD_OF_THE_WEAKEST",
        "scripts/check_answer_axes.py",
        '    weakest = min(measured, key=lambda item: item["value"])',
        '    weakest = max(measured, key=lambda item: item["value"])',
        (
            "apps/api/tests/test_answer_axes_composition.py::"
            "test_the_weakest_axis_is_named_not_just_counted",
        ),
    ),
    Mutant(
        # Сліпа вісь не є пройденою: вона могла б виявитись найслабшою, а найслабша і є
        # вироком. Знявши цю гілку, профіль зеленіє від відсутності звіту.
        "M362_BLIND_AXIS_COUNTS_AS_PASSED",
        "scripts/check_answer_axes.py",
        "    if unmeasured:",
        "    if False:",
        ("apps/api/tests/test_answer_axes_composition.py::test_a_blind_axis_is_not_a_passed_axis",),
    ),
    Mutant(
        # Голий домен, зарахований як посилання на документ, робить простежуваність
        # 100 % при 42 % реальних. Саме це число і є половиною ціннісної функції.
        "M363_BARE_DOMAIN_COUNTS_AS_A_DOCUMENT_LINK",
        "scripts/measure_corpus_integrity.py",
        "    bare = sum(1 for value in rows if value and _BARE_DOMAIN.fullmatch(value.strip()))",
        "    bare = 0",
        (
            "apps/api/tests/test_corpus_integrity.py::"
            "test_a_link_to_a_document_counts_and_a_link_to_the_portal_does_not",
        ),
    ),
    Mutant(
        "M187_DECLARATION_RECORDED_AS_VERIFIED",
        "apps/api/src/korpus/application/answer_audit.py",
        '                    "verified": False,',
        '                    "verified": True,',
        (
            "apps/api/tests/test_answers.py::test_the_operator_declaration_enters_the_audit_chain_marked_unverified",
        ),
    ),
    Mutant(
        "M188_DECLARATION_ACCEPTS_CONTROL_CHARACTERS",
        "apps/api/src/korpus/domain/models.py",
        '            raise ValueError("declared field contains control characters")',
        "            pass",
        ("apps/api/tests/test_answers.py::test_a_declaration_with_control_characters_is_refused",),
    ),
    Mutant(
        "M184_RESCISSION_WITHOUT_ENTITLEMENT",
        "apps/api/src/korpus/api/routes_review.py",
        "        if document is None or not policy.can_access_document(identity, document).allowed:",
        "        if document is None:",
        (
            "apps/api/tests/test_access_oracles.py::test_an_unentitled_reviewer_cannot_take_an_order_out_of_force",
        ),
    ),
    Mutant(
        # The exact-hash half of the same oracle. The code was careful not to return the
        # matched record and then revealed the same fact in prose.
        "M186_EXACT_DUPLICATE_CONFIRMS_UNREADABLE_CONTENT",
        "apps/api/src/korpus/application/ingestion.py",
        "                duplicate = None\n            else:",
        '                raise ValueError("duplicate source content already exists")\n'
        "            else:",
        (
            "apps/api/tests/test_access_oracles.py::"
            "test_the_exact_duplicate_check_does_not_confirm_unreadable_content",
        ),
    ),
    Mutant(
        # The near-duplicate probe returned a matched version id and a graded similarity
        # for material the caller cannot list. A yes/no oracle is a disclosure; a graded
        # one is a reconstruction method.
        "M185_NEAR_DUPLICATE_PROBE_IGNORES_COMPARTMENTS",
        "apps/api/src/korpus/infrastructure/repository.py",
        "            .join(documents, versions.c.document_id == documents.c.id)\n"
        "            .where(documents.c.corpus_id.in_(sorted(identity.corpora)))\n"
        "            .where(documents.c.access_tier <= int(identity.clearance))",
        "            .join(documents, versions.c.document_id == documents.c.id)",
        (
            "apps/api/tests/test_access_oracles.py::"
            "test_the_near_duplicate_probe_is_not_a_graded_content_oracle",
        ),
    ),
    Mutant(
        # Found 2026-08-06 by an adversarial review of the evidence path. The cache key
        # carried subject, clearance, roles and corpora; compartments decide which spans
        # retrieval returns, and entitlements are resolved per request — so a withdrawn
        # compartment kept granting evidence for the length of the TTL.
        "M183_CACHE_KEY_IGNORES_COMPARTMENTS",
        "apps/api/src/korpus/application/cache.py",
        '                ",".join(sorted(identity.compartments)),',
        "",
        (
            "apps/api/tests/test_query_cache.py::"
            "test_two_compartment_sets_do_not_share_a_cached_result",
        ),
    ),
    Mutant(
        # The malware scan on the *version* ingestion path — the same untrusted-bytes
        # surface, reached more easily: the document already exists and already passed
        # review. Split from M16, which covered both lines at once.
        "M181_MALWARE_SCAN_BYPASS_ON_VERSION_INGEST",
        "apps/api/src/korpus/application/ingestion.py",
        '                raise ValueError("supersedes_version_id must reference the same '
        'canonical document")\n        self.malware_scanner.scan(path)',
        '                raise ValueError("supersedes_version_id must reference the same '
        'canonical document")\n        None',
        (
            "apps/api/tests/test_v5_security_kernel.py::"
            "test_a_new_version_of_an_existing_document_is_scanned_too",
        ),
    ),
    Mutant(
        # The retriever's own default, which production never uses — `dependencies.py`
        # always passes the calibrated value — so it can drift from the function it
        # forwards to with nothing observing it.
        "M182_RETRIEVER_PER_VERSION_CAP_WIDENED",
        "apps/api/src/korpus/application/retrieval.py",
        "        authority_relevance_floor: float = 0.0,\n        per_version_cap: int = 1,",
        "        authority_relevance_floor: float = 0.0,\n        per_version_cap: int = 2,",
        (
            "apps/api/tests/test_authority_ranking.py::"
            "test_the_retriever_carries_the_same_cap_its_diversifier_defaults_to",
        ),
    ),
    Mutant(
        # The `complete` half of the lease check. A worker that does not hold the job
        # marking it succeeded records a version as ingested from bytes nobody parsed,
        # and the corpus then answers from spans that were never extracted.
        "M180_LEASE_OWNERSHIP_UNCHECKED_ON_COMPLETE",
        "apps/api/src/korpus/infrastructure/ingestion_jobs.py",
        "            if changed.rowcount != 1:\n"
        '                raise IngestionJobConflict("worker does not own active ingestion lease")',
        "            if changed.rowcount != 1:\n                pass",
        (
            "apps/api/tests/test_durable_ingestion_jobs.py::"
            "test_a_worker_cannot_mark_a_job_succeeded_that_it_does_not_hold",
        ),
    ),
    Mutant(
        # A second worker writing a result for a job it does not hold marks a version as
        # ingested from bytes nobody parsed. The claim was exclusive and the write was
        # not tested.
        # The same sentence guards `complete` and `fail`. `fail` reaches it through
        # `if row is None:`, `complete` through `if changed.rowcount != 1:`, so the
        # guard above disambiguates them. M180 is the `complete` side, the worse
        # one: a non-holder marking a job succeeded records a version as ingested
        # from bytes nobody parsed.
        "M176_LEASE_OWNERSHIP_UNCHECKED_ON_FAIL",
        "apps/api/src/korpus/infrastructure/ingestion_jobs.py",
        "            if row is None:\n"
        '                raise IngestionJobConflict("worker does not own active ingestion lease")',
        "            if row is None:\n                pass",
        (
            "apps/api/tests/test_durable_ingestion_jobs.py::"
            "test_a_worker_cannot_complete_a_job_it_does_not_hold",
        ),
    ),
    Mutant(
        # A timeout means part of the corpus *was* searched, so answering from what came
        # back is the tempting behaviour — from a candidate set the calibrated profile
        # never described, with nothing in the response saying the search was cut short.
        "M177_RETRIEVAL_DEADLINE_ANSWERS_FROM_A_PARTIAL_SEARCH",
        "apps/api/src/korpus/application/answer_query.py",
        '                "retrieval_deadline_exceeded",',
        '                "retrieval_dependency_unavailable",',
        (
            "apps/api/tests/test_answers.py::"
            "test_a_retrieval_deadline_abstains_rather_than_answering_from_a_partial_search",
        ),
    ),
    Mutant(
        "M173_UNKNOWN_ENVIRONMENT_VARIABLE_IGNORED",
        "apps/api/src/korpus/main.py",
        "    if unknown:",
        "    if False:",
        (
            "apps/api/tests/test_configuration_typos.py::"
            "test_the_app_refuses_to_start_on_an_unrecognised_variable",
        ),
    ),
    Mutant(
        "M174_TYPO_DETECTOR_ACCEPTS_EVERYTHING",
        "apps/api/src/korpus/config.py",
        '        if name.startswith("KORPUS_") and name not in known and name not in OPERATIONAL_VARIABLES',
        '        if name.startswith("KORPUS_")\n        and name not in known\n        and False\n        and name not in OPERATIONAL_VARIABLES',
        ("apps/api/tests/test_configuration_typos.py::test_a_misspelled_setting_is_named",),
    ),
    Mutant(
        "M175_OPERATIONAL_VARIABLES_REPORTED_AS_TYPOS",
        "apps/api/src/korpus/config.py",
        '        name\n        for name in environ\n        if name.startswith("KORPUS_") and name not in known and name not in OPERATIONAL_VARIABLES',
        '        name for name in environ if name.startswith("KORPUS_") and name not in known and True',
        ("apps/api/tests/test_configuration_typos.py::test_operational_variables_are_not_flagged",),
    ),
    Mutant(
        "M124_UNOBSERVED_ARTEFACT_TREATED_AS_IN_SYNC",
        "apps/api/src/korpus/application/environment_drift.py",
        "        if path not in observed:",
        "        if False:",
        (
            "apps/api/tests/test_environment_drift.py::"
            "test_absent_from_observation_is_unobserved_not_in_sync",
        ),
    ),
    Mutant(
        "M125_CHANGED_DIGEST_NOT_REPORTED",
        "apps/api/src/korpus/application/environment_drift.py",
        "        elif seen != approved:",
        "        elif False:",
        (
            "apps/api/tests/test_environment_drift.py::"
            "test_changed_digest_is_drift_and_carries_both_sides",
        ),
    ),
    Mutant(
        "M126_UNREADABLE_ARTEFACT_REPORTED_AS_DRIFT",
        "apps/api/src/korpus/application/environment_drift.py",
        "        if seen is None:",
        "        if False:",
        (
            "apps/api/tests/test_environment_drift.py::"
            "test_present_but_unreadable_is_unobserved_not_drift",
        ),
    ),
    Mutant(
        "M127_UNDECLARED_ARTEFACT_IGNORED",
        "apps/api/src/korpus/application/environment_drift.py",
        "    for path in sorted(set(observed) - set(desired)):",
        "    for path in ():",
        ("apps/api/tests/test_environment_drift.py::test_undeclared_artefact_is_extra_not_drift",),
    ),
    Mutant(
        "M128_DRIFTED_ENVIRONMENT_NOT_BLOCKED",
        "apps/api/src/korpus/application/environment_drift.py",
        "    if report.in_sync:\n"
        '        return False, "the environment matches the approved desired state"',
        '    if True:\n        return False, "the environment matches the approved desired state"',
        (
            "apps/api/tests/test_environment_drift.py::"
            "test_changed_digest_is_drift_and_carries_both_sides",
        ),
    ),
    Mutant(
        "M131_STALE_OBSERVATION_ACCEPTED",
        "apps/api/src/korpus/application/environment_drift.py",
        "    if age > max_age_seconds:",
        "    if False:",
        (
            "apps/api/tests/test_environment_drift.py::"
            "test_an_observation_past_the_limit_is_refused",
        ),
    ),
    Mutant(
        "M132_UNDATED_OBSERVATION_ASSUMED_FRESH",
        "apps/api/src/korpus/application/environment_drift.py",
        "    if not observed_at:",
        "    if False:",
        (
            "apps/api/tests/test_environment_drift.py::"
            "test_an_observation_without_a_timestamp_is_refused",
        ),
    ),
    Mutant(
        "M133_NAIVE_TIMESTAMP_ASSUMED_UTC",
        "apps/api/src/korpus/application/environment_drift.py",
        "    if taken.tzinfo is None:",
        "    if False:",
        (
            "apps/api/tests/test_environment_drift.py::"
            "test_a_naive_timestamp_is_refused_rather_than_assumed_utc",
        ),
    ),
    Mutant(
        "M129_EMPTY_DESIRED_STATE_ACCEPTED",
        "apps/api/src/korpus/application/environment_drift.py",
        '        raise ValueError("desired-state manifest has no records list")',
        "        return {}",
        (
            "apps/api/tests/test_environment_drift.py::"
            "test_manifest_without_records_refuses_rather_than_returning_empty",
        ),
    ),
    # ---------------------------------------------------------------- ACT-001
    # Every mutant below turns a narrowing rule into a widening one, or removes a
    # refusal. They are the shapes the account/billing/conversation layer fails in, and
    # each one would leave the system running and answering.
    Mutant(
        "M130_ENTITLEMENT_UNIONS_INSTEAD_OF_INTERSECTS",
        "apps/api/src/korpus/application/paid_access.py",
        "        allowed = permitted & entitlement.entitled_corpora",
        "        allowed = permitted | entitlement.entitled_corpora",
        (
            "apps/api/tests/test_entitlement_gate.py::"
            "test_an_active_subscription_permits_only_what_it_pays_for",
        ),
    ),
    Mutant(
        "M131_PAST_DUE_KEEPS_PAYING",
        "apps/api/src/korpus/domain/tenancy.py",
        "        return self is SubscriptionStatus.ACTIVE",
        "        return self in {SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE}",
        ("apps/api/tests/test_entitlement_gate.py::test_a_past_due_subscription_pays_for_nothing",),
    ),
    Mutant(
        "M132_CANCELLED_SUBSCRIPTION_CAN_BE_RESURRECTED",
        "apps/api/src/korpus/domain/tenancy.py",
        "    SubscriptionStatus.CANCELED: frozenset(),",
        "    SubscriptionStatus.CANCELED: frozenset({SubscriptionStatus.ACTIVE}),",
        (
            "apps/api/tests/test_billing_events.py::"
            "test_a_canceled_subscription_cannot_be_reactivated",
        ),
    ),
    Mutant(
        "M133_EXPIRED_PERIOD_STILL_PAYS",
        "apps/api/src/korpus/domain/tenancy.py",
        "        if self.current_period_end is not None and moment >= self.current_period_end:",
        "        if False:",
        (
            "apps/api/tests/test_entitlement_gate.py::"
            "test_an_expired_period_stops_paying_without_any_event_arriving",
        ),
    ),
    Mutant(
        "M134_DISABLED_ACCOUNT_STILL_ENTITLED",
        "apps/api/src/korpus/application/paid_access.py",
        "        if account.status is not AccountStatus.ACTIVE:",
        "        if False:",
        (
            "apps/api/tests/test_entitlement_gate.py::"
            "test_a_disabled_account_entitles_nothing_however_much_it_paid",
        ),
    ),
    Mutant(
        "M135_DISABLED_ACCOUNT_ADMITTED",
        "apps/api/src/korpus/application/accounts.py",
        "        if account.status is not AccountStatus.ACTIVE:",
        "        if False:",
        (
            "apps/api/tests/test_account_domain.py::"
            "test_a_disabled_account_cannot_use_protected_functionality",
        ),
    ),
    Mutant(
        "M136_CONVERSATION_OWNERSHIP_DROPPED",
        "apps/api/src/korpus/infrastructure/conversation_repository.py",
        "                    .where(conversations.c.account_id == str(account_id))\n"
        "                )\n"
        "                .mappings()\n"
        "                .first()",
        "                )\n                .mappings()\n                .first()",
        ("apps/api/tests/test_conversations.py::test_a_conversation_is_visible_only_to_its_owner",),
    ),
    Mutant(
        "M137_DUPLICATE_BILLING_EVENT_REAPPLIED",
        "apps/api/src/korpus/application/subscriptions.py",
        "        if existing is not None:",
        "        if False:",
        ("apps/api/tests/test_billing_events.py::test_a_redelivered_event_changes_nothing",),
    ),
    Mutant(
        "M138_UNSIGNED_BILLING_EVENT_ACCEPTED",
        "apps/api/src/korpus/infrastructure/deterministic_billing.py",
        '        if not signature:\n            raise ValueError("unsigned billing event")',
        "        if not signature:\n            signature = self.sign(payload)",
        ("apps/api/tests/test_billing_events.py::test_an_unsigned_event_is_refused",),
    ),
    Mutant(
        "M139_REPLAYED_EVENT_MOVES_STATE_BACKWARDS",
        "apps/api/src/korpus/application/billing_adjudication.py",
        "        if subscription.last_event_at is not None and occurred < subscription.last_event_at:",
        "        if False:  # noqa",
        (
            "apps/api/tests/test_billing_events.py::test_a_replayed_older_event_does_not_move_the_subscription_backwards",
        ),
    ),
    Mutant(
        "M140_LOCAL_ONLY_ACCEPTS_ARBITRARY_DNS_NAME",
        "apps/api/src/korpus/application/egress.py",
        "        except ValueError:\n            return False",
        "        except ValueError:\n            return True",
        (
            "apps/api/tests/test_model_egress.py::test_local_only_refuses_arbitrary_dns_names_even_if_the_first_lookup_would_be_private",
        ),
    ),
    Mutant(
        "M141_MODEL_DISABLED_STILL_CALLS_OUT",
        "apps/api/src/korpus/application/egress.py",
        "        if self.posture is EgressPosture.MODEL_DISABLED:",
        "        if False:",
        ("apps/api/tests/test_model_egress.py::test_model_disabled_refuses_even_a_local_endpoint",),
    ),
    Mutant(
        "M142_IDENTITY_CLAIMS_GRANT_AUTHORIZATION",
        "apps/api/src/korpus/application/accounts.py",
        "        if leaked:",
        "        if False:",
        (
            "apps/api/tests/test_account_domain.py::"
            "test_identity_claims_carrying_authorization_are_refused_not_filtered",
        ),
    ),
    Mutant(
        "M143_ENTITLEMENT_CHECK_SKIPPED_WHEN_EMPTY",
        "apps/api/src/korpus/application/paid_access.py",
        "        if not allowed:",
        "        if False:",
        (
            "apps/api/tests/test_entitlement_gate.py::"
            "test_without_an_active_subscription_the_paid_corpus_is_denied",
        ),
    ),
    Mutant(
        "M144_CONVERSATION_LIST_TRUNCATES_IN_SILENCE",
        "apps/api/src/korpus/infrastructure/conversation_repository.py",
        "        return [_conversation(row) for row in rows[:wanted]], len(rows) > wanted",
        "        return [_conversation(row) for row in rows[:wanted]], False",
        ("apps/api/tests/test_conversations.py::test_a_truncated_list_says_it_was_truncated",),
    ),
    Mutant(
        "M145_TRANSCRIPT_HIDES_ITS_NEWEST_TURNS",
        "apps/api/src/korpus/infrastructure/conversation_repository.py",
        "        return [_message(row) for row in rows[:wanted]], len(rows) > wanted",
        "        return [_message(row) for row in rows[:wanted]], False",
        (
            "apps/api/tests/test_conversations.py::"
            "test_a_truncated_transcript_says_its_newest_turns_are_missing",
        ),
    ),
    Mutant(
        "M146_PAGE_TWO_REPEATS_PAGE_ONE",
        "apps/api/src/korpus/infrastructure/conversation_repository.py",
        "            .limit(wanted + 1)\n            .offset(max(0, offset))\n        )\n"
        "        if not include_archived:",
        "            .limit(wanted + 1)\n        )\n        if not include_archived:",
        ("apps/api/tests/test_conversations.py::test_a_truncated_list_says_it_was_truncated",),
    ),
    Mutant(
        "M147_ANSWER_BOUND_REMOVED",
        "apps/api/src/korpus/api/answering.py",
        "        with admission.acquire(identity.subject):",
        "        with nullcontext():",
        (
            "apps/api/tests/test_tenancy_api.py::"
            "test_the_conversation_route_sheds_load_like_the_stateless_one",
        ),
    ),
    Mutant(
        "M148_CONVERSATION_ROUTE_BYPASSES_THE_BOUND",
        "apps/api/src/korpus/api/routes_tenancy.py",
        "        answer = await run_in_threadpool(\n"
        "            bounded_answer, answers, identity, scoped, admission, observability\n"
        "        )",
        "        answer = await run_in_threadpool(answers.execute, identity, scoped)",
        (
            "apps/api/tests/test_answer_paths_are_bounded.py::"
            "test_every_answer_path_goes_through_the_shared_bound",
        ),
        full_copy=True,
    ),
    Mutant(
        "M149_UNDECLARED_RETENTION_READS_AS_COMPLIANT",
        "apps/api/src/korpus/application/conversation_retention.py",
        '            return "NOT_DECLARED"',
        '            return "NOTHING_DUE"',
        (
            "apps/api/tests/test_conversation_retention.py::"
            "test_no_declared_window_is_reported_as_undecided_not_as_compliant",
        ),
    ),
    Mutant(
        "M150_RETENTION_BOUNDARY_DELETES_AT_THE_WINDOW",
        "apps/api/src/korpus/application/conversation_retention.py",
        "        expired = aware < cutoff",
        "        expired = aware <= cutoff",
        (
            "apps/api/tests/test_conversation_retention.py::"
            "test_the_boundary_keeps_rather_than_deletes",
        ),
    ),
    Mutant(
        "M151_RETENTION_APPLIES_WITHOUT_A_DECLARED_WINDOW",
        "scripts/conversation_retention.py",
        "        if arguments.apply and plan.state is RetentionState.NOT_DECLARED:",
        "        if False:",
        (
            "apps/api/tests/test_conversation_retention.py::"
            "test_the_script_refuses_to_apply_a_policy_nobody_declared",
        ),
    ),
    Mutant(
        "M152_A_DISABLED_ADMIN_MAY_STILL_ADMINISTER",
        "apps/api/src/korpus/api/routes_admin.py",
        "    account_for(service, identity)\n    try:\n"
        "        PolicyEngine().require(identity, ACCOUNT_MANAGE)",
        "    try:\n        PolicyEngine().require(identity, ACCOUNT_MANAGE)",
        (
            "apps/api/tests/test_account_administration.py::"
            "test_a_disabled_administrator_cannot_administer",
        ),
    ),
    Mutant(
        "M153_ANY_ROLE_MAY_SWITCH_A_PERSON_OFF",
        "apps/api/src/korpus/api/routes_admin.py",
        "        PolicyEngine().require(identity, ACCOUNT_MANAGE)",
        '        PolicyEngine().require(identity, "answer:read")',
        (
            "apps/api/tests/test_account_administration.py::"
            "test_only_an_administrator_may_switch_a_person_off",
        ),
    ),
    Mutant(
        "M154_AN_ADMIN_CAN_LOCK_THEMSELVES_OUT",
        "apps/api/src/korpus/api/routes_admin.py",
        "    if target.auth_subject == identity.subject and "
        "body.status == AccountStatus.DISABLED.value:",
        "    if False:",
        (
            "apps/api/tests/test_account_administration.py::"
            "test_an_administrator_cannot_disable_the_account_they_are_using",
        ),
    ),
    Mutant(
        "M155_A_CHECKED_PERMISSION_NEED_NOT_BE_NAMED",
        "apps/api/src/korpus/application/policy.py",
        '        "account:manage",\n    }\n)',
        "    }\n)",
        (
            "apps/api/tests/test_permission_contract.py::"
            "test_every_permission_a_route_requires_is_a_permission_the_system_names",
        ),
    ),
    Mutant(
        "M156_AN_ORDINARY_ROLE_IS_GRANTED_ACCOUNT_MANAGEMENT",
        "apps/api/src/korpus/application/policy.py",
        '    "auditor": frozenset({"audit:read", "audit:verify", "document:list"}),',
        '    "auditor": frozenset({"audit:read", "audit:verify", "document:list", '
        '"account:manage"}),',
        (
            "apps/api/tests/test_permission_contract.py::"
            "test_account_management_is_held_by_no_ordinary_role",
        ),
    ),
    Mutant(
        "M157_LINK_LOCAL_ACCEPTED_AS_LOCAL",
        "apps/api/src/korpus/application/egress.py",
        "        if parsed.is_link_local:\n            return False",
        "        if False:\n            return False",
        (
            "apps/api/tests/test_model_egress.py::test_local_only_refuses_the_cloud_metadata_endpoint",
        ),
    ),
    Mutant(
        "M158_READINESS_LEAKS_SNAPSHOT_WITHOUT_TOKEN",
        "apps/api/src/korpus/api/routes_health.py",
        "    expected = settings.resolved_metrics_token\n    if expected is None:\n        return True",
        "    expected = settings.resolved_metrics_token\n    if True:\n        return True",
        (
            "apps/api/tests/test_infrastructure_hardening.py::test_not_ready_hides_the_internal_snapshot_without_the_metrics_token",
        ),
    ),
    Mutant(
        "M159_ORPHAN_REAPER_TERMINATES_LIVE_JOBS",
        "apps/api/src/korpus/infrastructure/ingestion_jobs.py",
        "                .where(ingestion_jobs.c.attempts >= ingestion_jobs.c.max_attempts)",
        "                .where(ingestion_jobs.c.attempts >= 0)",
        (
            "apps/api/tests/test_reliability_degradation.py::"
            "test_a_crashed_worker_leaves_no_zombie_running_job",
        ),
    ),
    Mutant(
        "M160_BILLING_REPLAY_GUARD_USES_PROCESSING_CLOCK",
        "apps/api/src/korpus/application/billing_adjudication.py",
        "        if subscription.last_event_at is not None and occurred < subscription.last_event_at:",
        "        if subscription.last_event_at is not None and occurred < subscription.updated_at:",
        (
            "apps/api/tests/test_billing_events.py::test_a_legitimate_in_order_event_is_not_rejected_as_a_replay",
        ),
    ),
    Mutant(
        "M161_INTEGRITY_ERROR_SWALLOWED_AS_DUPLICATE",
        "apps/api/src/korpus/infrastructure/billing_repository.py",
        "            if idempotency:\n                return BillingEventResult.DUPLICATE\n"
        "            raise",
        "            if True:\n                return BillingEventResult.DUPLICATE\n"
        "            raise",
        (
            "apps/api/tests/test_billing_events.py::"
            "test_a_non_idempotency_integrity_error_is_not_swallowed_as_a_duplicate",
        ),
    ),
    Mutant(
        "M162_DB_OUTAGE_NOT_RETRYABLE",
        "apps/api/src/korpus/api/routes_corpus.py",
        '                detail="upload staging is full; retry shortly",\n                headers={"Retry-After": "2"},',
        '                detail="upload staging is full; retry shortly",\n                headers={},',
        (
            "apps/api/tests/test_reliability_degradation.py::test_a_full_upload_spool_is_a_503_not_a_500",
        ),
    ),
    Mutant(
        # GOV-006. The egress ceiling admits material *at* the ceiling and refuses above
        # it; `<` instead of `<=` would withhold public material from the composer even at
        # a public ceiling, disabling the feature for the exact case it must permit.
        "M163_EGRESS_CEILING_OFF_BY_ONE",
        "apps/api/src/korpus/application/egress.py",
        "        return int(max_tier) <= int(self.max_external_tier)",
        "        return int(max_tier) < int(self.max_external_tier)",
        (
            "apps/api/tests/test_egress_material_ceiling.py::"
            "test_permits_material_is_a_ceiling_not_a_floor",
        ),
    ),
    Mutant(
        # The ceiling applies only to external egress. Flipping this to refuse under
        # local_only/model_disabled would deny a local model material it may lawfully
        # arrange, because that material never leaves the deployment.
        "M164_EGRESS_CEILING_APPLIES_WHEN_LOCAL",
        "apps/api/src/korpus/application/egress.py",
        "        if self.posture is not EgressPosture.EXTERNAL_ALLOWED:\n            return True",
        "        if self.posture is not EgressPosture.EXTERNAL_ALLOWED:\n            return False",
        (
            "apps/api/tests/test_egress_material_ceiling.py::"
            "test_permits_material_ignores_the_ceiling_when_the_model_is_local",
        ),
    ),
    Mutant(
        # A span whose tier the eligible set does not carry is assumed RESTRICTED. Assuming
        # PUBLIC is the leak: a claim whose provenance the service cannot see would be sent
        # to a vendor as if it were public.
        "M165_EGRESS_UNKNOWN_SPAN_DEFAULT_LEAK",
        "apps/api/src/korpus/application/answer_query.py",
        "                tier_by_span.get(str(span_id), AccessTier.RESTRICTED)",
        "                tier_by_span.get(str(span_id), AccessTier.PUBLIC)",
        (
            "apps/api/tests/test_egress_material_ceiling.py::"
            "test_a_claim_backed_by_an_unknown_span_is_treated_as_the_most_restrictive",
        ),
    ),
    Mutant(
        # The gate itself. Bypassing it sends restricted spans to an external composer.
        "M166_EGRESS_GATE_BYPASSED",
        "apps/api/src/korpus/application/answer_query.py",
        "        if not self._composition_egress_permitted(claims, eligible):\n"
        '            return None, "egress_tier_exceeded"',
        '        if False:\n            return None, "egress_tier_exceeded"',
        (
            "apps/api/tests/test_egress_material_ceiling.py::"
            "test_restricted_material_never_reaches_an_external_composer",
        ),
    ),
    Mutant(
        "M208_WEBHOOK_DECLARED_SIZE_LIMIT_BYPASSED",
        "apps/api/src/korpus/api/request_limits.py",
        "            if int(declared) > MAX_WEBHOOK_BYTES:",
        "            if False:",
        (
            "apps/api/tests/test_tenancy_threats.py::test_t12a_declared_oversize_is_refused_before_stream_consumption",
        ),
    ),
    Mutant(
        "M209_WEBHOOK_STREAM_SIZE_LIMIT_BYPASSED",
        "apps/api/src/korpus/api/request_limits.py",
        "        if len(payload) + len(chunk) > MAX_WEBHOOK_BYTES:",
        "        if False:",
        (
            "apps/api/tests/test_tenancy_threats.py::test_t12b_chunked_oversize_stops_at_the_first_excess_chunk",
        ),
    ),
    Mutant(
        "M210_ADMIN_UNKNOWN_PERMISSION_FAILS_OPEN",
        "apps/api/src/korpus/application/policy.py",
        '        if permission not in KNOWN_PERMISSIONS:\n            raise AuthorizationError(f"unknown permission: {permission}")',
        '        if False:\n            raise AuthorizationError(f"unknown permission: {permission}")',
        (
            "apps/api/tests/test_permission_contract.py::test_admin_wildcard_does_not_authorize_an_unknown_permission",
        ),
    ),
    Mutant(
        "M211_INTERNAL_REDTEAM_PROMOTED",
        "apps/api/src/korpus/application/production_assurance_external.py",
        '        == external.get("redteam_evidence_class"),',
        '        != external.get("redteam_evidence_class"),',
        (
            "apps/api/tests/test_production_assurance.py::test_internal_redteam_cannot_promote_production",
        ),
    ),
    Mutant(
        "M212_STALE_PRODUCTION_GATE_ACCEPTED",
        "apps/api/src/korpus/application/production_assurance.py",
        '        checks[f"{gate_id}.source_bound"] = gate.get("source_tree_sha256") == source_digest',
        '        checks[f"{gate_id}.source_bound"] = True',
        (
            "apps/api/tests/test_production_assurance.py::test_stale_gate_digest_is_rejected_even_if_it_says_pass",
        ),
    ),
    Mutant(
        "M213_NON_POSTGRES_BACKEND_PROMOTED",
        "apps/api/src/korpus/application/production_assurance_external.py",
        '        "postgres.real_backend": postgres.get("backend") == external.get("postgres_backend"),',
        '        "postgres.real_backend": True,',
        (
            "apps/api/tests/test_production_assurance.py::test_non_postgres_backend_cannot_promote_production",
        ),
    ),
    Mutant(
        "M214_PARTIAL_SUPPLY_CHAIN_PROMOTED",
        "apps/api/src/korpus/application/production_assurance_external.py",
        '        "supply_chain.complete": supply.get("completeness")\n        == external.get("supply_chain_completeness"),',
        '        "supply_chain.complete": True,',
        (
            "apps/api/tests/test_production_assurance.py::test_partial_supply_chain_evidence_cannot_promote_production",
        ),
    ),
    Mutant(
        "M215_PARTIAL_MUTATION_SCOPE_PROMOTED",
        "apps/api/src/korpus/application/production_assurance_external.py",
        '        "mutation.full_catalogue": mutation.get("scope") == external.get("mutation_scope"),',
        '        "mutation.full_catalogue": True,',
        (
            "apps/api/tests/test_production_assurance.py::test_partial_mutation_scope_cannot_promote_production",
        ),
    ),
    Mutant(
        "M216_SECURITY_METRIC_LABEL_VOCABULARY_BYPASSED",
        "apps/api/src/korpus/infrastructure/observability.py",
        "        if event not in SECURITY_EVENTS or outcome not in SECURITY_OUTCOMES:",
        "        if False:",
        (
            "apps/api/tests/test_observability.py::test_security_metrics_reject_unbounded_or_invented_labels",
        ),
    ),
    Mutant(
        "M217_EXTERNAL_REDTEAM_ATTESTATION_BYPASSED",
        "apps/api/src/korpus/application/production_assurance_external.py",
        '        "redteam.attestation_verified": redteam.get("attestation_verified")\n        is external.get("redteam_attestation_verified"),',
        '        "redteam.attestation_verified": True,',
        (
            "apps/api/tests/test_production_assurance.py::test_self_declared_external_redteam_without_trusted_attestation_is_rejected",
        ),
    ),
    Mutant(
        "M218_UNTRUSTED_REDTEAM_SIGNER_ACCEPTED",
        "apps/api/src/korpus/application/production_assurance_external.py",
        '        "redteam.trusted_signer": redteam.get("trusted_signer")\n        is external.get("redteam_trusted_signer_required"),',
        '        "redteam.trusted_signer": True,',
        (
            "apps/api/tests/test_production_assurance.py::test_self_declared_external_redteam_without_trusted_attestation_is_rejected",
        ),
    ),
    Mutant(
        "M219_LOCAL_LOAD_PROMOTED_TO_PRODUCTION",
        "apps/api/src/korpus/application/production_reliability.py",
        '        "load_environment": load.get("environment_class") in ALLOWED_ENVIRONMENTS,',
        '        "load_environment": True,',
        (
            "apps/api/tests/test_production_reliability.py::test_local_load_and_fixture_recovery_cannot_promote_production_even_if_signed",
        ),
    ),
    Mutant(
        "M220_FIXTURE_RECOVERY_PROMOTED_TO_PRODUCTION",
        "apps/api/src/korpus/application/production_reliability.py",
        '        "recovery_environment": recovery.get("environment_class") in ALLOWED_ENVIRONMENTS,',
        '        "recovery_environment": True,',
        (
            "apps/api/tests/test_production_reliability.py::test_local_load_and_fixture_recovery_cannot_promote_production_even_if_signed",
        ),
    ),
    Mutant(
        "M221_STALE_RELIABILITY_LOAD_ACCEPTED",
        "apps/api/src/korpus/application/production_reliability.py",
        '        "load_source_bound": _bound(load, source, release),',
        '        "load_source_bound": True,',
        (
            "apps/api/tests/test_production_reliability.py::test_reliability_evidence_from_another_tree_is_rejected",
        ),
    ),
    Mutant(
        "M222_ENGINEERING_REPORT_DIGEST_DOMAIN_CONFUSED",
        "scripts/run_engineering_production_gate.py",
        '        "source_bound": report.get("evidence_source_sha256") == source,',
        '        "source_bound": report.get("source_tree_sha256") == source,',
        (
            "apps/api/tests/test_production_assurance.py::test_engineering_gate_uses_evidence_digest_not_git_digest_domain",
        ),
    ),
    Mutant(
        "M223_PACKAGE_MODE_INTEGRITY_BYPASSED",
        "scripts/manifest_lib/integrity.py",
        '    if record.get("mode") != actual_mode:',
        "    if False:",
        (
            "apps/api/tests/test_package_mode_integrity.py::test_package_verifier_refuses_lost_executable_mode",
        ),
    ),
    Mutant(
        "M224_MANIFEST_ROOT_IGNORES_MODE",
        "scripts/manifest_lib/integrity.py",
        "        f\"{item['path']}\\0{item['mode']}\\0{item['sha256']}\\n\" for item in records",
        "        f\"{item['path']}\\0{item['sha256']}\\n\" for item in records",
        (
            "apps/api/tests/test_manifest_generation.py::test_manifest_root_changes_when_only_mode_changes",
        ),
    ),
    Mutant(
        "M225_UNTRUSTED_ASSURANCE_SIGNER_ACCEPTED",
        "apps/api/src/korpus/application/attested_evidence.py",
        '        "trusted_signer": bool(fingerprint) and fingerprint in set(trusted_fingerprints),',
        '        "trusted_signer": True,',
        (
            "apps/api/tests/test_attested_evidence.py::test_valid_but_untrusted_self_signature_is_not_trust_evidence",
        ),
    ),
    Mutant(
        "M226_TAMPERED_ASSURANCE_SIGNATURE_ACCEPTED",
        "apps/api/src/korpus/application/attested_evidence.py",
        '        "signature": signature_ok,',
        '        "signature": True,',
        (
            "apps/api/tests/test_attested_evidence.py::test_tampered_evidence_breaks_signature_and_digest_binding",
        ),
    ),
    Mutant(
        "M227_ENVIRONMENT_ATTESTATION_VERIFICATION_BYPASSED",
        "apps/api/src/korpus/application/assurance_evidence.py",
        '        f"{prefix}_attestation_verified": verdict.cryptographically_valid,',
        '        f"{prefix}_attestation_verified": True,',
        (
            "apps/api/tests/test_production_reliability.py::test_production_like_strings_without_attestations_cannot_promote_reliability",
        ),
    ),
    Mutant(
        "M228_ENVIRONMENT_TRUSTED_SIGNER_BYPASSED",
        "apps/api/src/korpus/application/assurance_evidence.py",
        '        f"{prefix}_trusted_signer": verdict.trusted_signer,',
        '        f"{prefix}_trusted_signer": True,',
        (
            "apps/api/tests/test_production_reliability.py::test_production_like_strings_without_attestations_cannot_promote_reliability",
        ),
    ),
    Mutant(
        "M229_SECURITY_SCANNER_SET_EMPTIED",
        "apps/api/src/korpus/application/supply_chain_scanners.py",
        'EXPECTED_SECURITY_SCANNERS = frozenset({"gitleaks", "pip-audit:runtime", "pip-audit:dev", "trivy"})',
        "EXPECTED_SECURITY_SCANNERS = frozenset()",
        (
            "apps/api/tests/test_supply_chain_evidence_boundary.py::test_scanner_summary_status_string_alone_is_not_clean",
        ),
    ),
    Mutant(
        "M230_NON_CYCLONEDX_SBOM_ACCEPTED",
        "apps/api/src/korpus/application/assurance_evidence.py",
        '        data.get("bomFormat") == "CycloneDX"',
        "        True",
        (
            "apps/api/tests/test_supply_chain_evidence_boundary.py::test_container_sbom_filename_without_cyclonedx_payload_is_not_evidence",
        ),
    ),
    Mutant(
        "M231_INCOMPLETE_SOURCE_SBOM_ACCEPTED",
        "apps/api/src/korpus/application/assurance_evidence.py",
        "    return all((name, version) in components for name, version in locked.items())",
        "    return True",
        (
            "apps/api/tests/test_supply_chain_evidence_boundary.py::test_source_sbom_must_cover_every_locked_component",
        ),
    ),
    Mutant(
        "M232_STALE_SUPPLY_CHAIN_MANIFEST_ACCEPTED",
        "apps/api/src/korpus/application/assurance_evidence.py",
        '        and manifest.get("source_tree_sha256") == source',
        "        and True",
        (
            "apps/api/tests/test_supply_chain_evidence_boundary.py::test_supply_chain_manifest_from_another_source_tree_is_rejected",
        ),
    ),
    Mutant(
        "M233_TAMPERED_SUPPLY_CHAIN_ARTIFACT_ACCEPTED",
        "apps/api/src/korpus/application/assurance_evidence.py",
        '            and declared[name].get("sha256") == hashlib.sha256(data).hexdigest()',
        "            and True",
        (
            "apps/api/tests/test_supply_chain_evidence_boundary.py::test_supply_chain_manifest_is_bound_to_artifact_bytes",
        ),
    ),
    Mutant(
        "M234_UNMANAGED_DISTRIBUTIONS_ACCEPTED",
        "apps/api/src/korpus/application/exact_environment.py",
        '        "no_unmanaged_distributions": not extras,',
        '        "no_unmanaged_distributions": True,',
        (
            "apps/api/tests/test_exact_environment_evidence.py::test_unmanaged_distribution_prevents_exact_environment_claim",
        ),
    ),
    Mutant(
        "M235_WRONG_PRODUCTION_PYTHON_ACCEPTED",
        "apps/api/src/korpus/application/exact_environment.py",
        '        "production_python_exact": python_version == required_python,',
        '        "production_python_exact": True,',
        (
            "apps/api/tests/test_exact_environment_evidence.py::test_wrong_python_patch_version_prevents_exact_environment_claim",
        ),
    ),
    Mutant(
        "M236_FORGED_PRODUCTION_REPORT_BYPASSES_RECOMPUTATION",
        "apps/api/src/korpus/application/production_report_verification.py",
        '        "recomputed_pass": verdict.passed,',
        '        "recomputed_pass": True,',
        (
            "apps/api/tests/test_production_report_verification.py::test_forged_pass_report_cannot_override_failing_current_gate",
        ),
    ),
    Mutant(
        "M237_STALE_PRODUCTION_GATE_HASH_ACCEPTED",
        "apps/api/src/korpus/application/production_report_verification.py",
        '        "gate_hashes_current": report.get("gate_sha256") == dict(gate_sha256),',
        '        "gate_hashes_current": True,',
        (
            "apps/api/tests/test_production_report_verification.py::test_stale_gate_hashes_are_rejected_even_when_gate_payloads_match",
        ),
    ),
    Mutant(
        "M238_UNSIGNED_PRODUCTION_ASSURANCE_ACCEPTED",
        "apps/api/src/korpus/application/production_report_verification.py",
        '        "assurance_attestation_verified": attestation_verified,',
        '        "assurance_attestation_verified": True,',
        (
            "apps/api/tests/test_production_report_verification.py::test_unsigned_or_untrusted_production_assurance_report_is_rejected",
        ),
    ),
    Mutant(
        "M239_UNTRUSTED_PRODUCTION_ASSURANCE_SIGNER_ACCEPTED",
        "apps/api/src/korpus/application/production_report_verification.py",
        '        "assurance_trusted_signer": trusted_signer,',
        '        "assurance_trusted_signer": True,',
        (
            "apps/api/tests/test_production_report_verification.py::test_unsigned_or_untrusted_production_assurance_report_is_rejected",
        ),
    ),
    Mutant(
        "M240_RELEASE_TRUST_REQUIREMENT_IGNORED",
        "scripts/release_attestation.py",
        '    if not require_trusted:\n        checks.pop("trusted_signer", None)',
        '    if True:\n        checks.pop("trusted_signer", None)',
        (
            "apps/api/tests/test_release_attestation_trust.py::test_release_attestation_requires_pretrusted_signer",
        ),
    ),
    Mutant(
        "M241_SUBJECT_OVERLOAD_REASON_COLLAPSED",
        "apps/api/src/korpus/application/overload.py",
        '    SUBJECT_SHARE = "subject_share_exhausted"',
        '    SUBJECT_SHARE = "global_capacity_exhausted"',
        (
            "apps/api/tests/test_resilience_and_audit_scope.py::"
            "test_one_subject_cannot_take_the_whole_service",
        ),
    ),
    Mutant(
        "M242_SUBJECT_THROTTLE_MISLABELED_503",
        "apps/api/src/korpus/api/overload_http.py",
        "        status.HTTP_429_TOO_MANY_REQUESTS",
        "        status.HTTP_503_SERVICE_UNAVAILABLE",
        (
            "apps/api/tests/test_overload_http.py::"
            "test_subject_share_exhaustion_is_http_429_with_retry_after",
        ),
    ),
    Mutant(
        "M243_BAD_LOAD_SLO_ACCEPTED",
        "apps/api/src/korpus/application/production_reliability.py",
        "        **evaluate_load_slos(load),",
        "        **{},",
        (
            "apps/api/tests/test_production_reliability.py::"
            "test_signed_bad_load_cannot_pass_reliability_quality_predicates",
        ),
    ),
    Mutant(
        "M244_UNPROTECTED_CI_RUNTIME_TRUST_ACCEPTED",
        "apps/api/src/korpus/application/assurance_trust.py",
        '    if (\n        injected\n        and os.getenv("GITLAB_CI") == "true"\n        and os.getenv("CI_COMMIT_REF_PROTECTED") != "true"\n    ):',
        "    if False:",
        (
            "apps/api/tests/test_assurance_trust.py::"
            "test_runtime_trust_root_is_refused_on_unprotected_ci",
        ),
    ),
    Mutant(
        "M245_PARTIAL_EXTERNAL_RELIABILITY_EVIDENCE_ACCEPTED",
        "scripts/stage_external_production_evidence.py",
        "    if len(supplied) != len(specs):",
        "    if False:",
        (
            "apps/api/tests/test_external_production_evidence_staging.py::"
            "test_partial_group_fails_closed",
        ),
    ),
    Mutant(
        "M246_CANONICAL_LOAD_EVIDENCE_REGISTRY_PATH_REVERTED",
        "scripts/evidence_registry.py",
        '    "load-probe.json": "latency and saturation with the conditions attached",',
        '    "load-probe-api.json": "latency and saturation with the conditions attached",',
        (
            "apps/api/tests/test_ci_production_evidence_plumbing.py::"
            "test_evidence_registry_tracks_the_canonical_load_report_name",
        ),
    ),
    Mutant(
        "M247_EXTERNAL_REDTEAM_RUNTIME_TRUST_DISCONNECTED",
        "scripts/validate_external_redteam_evidence.py",
        '    trusted = trusted_fingerprints(\n        TRUST, "ed25519_public_key_sha256", "KORPUS_TRUSTED_EXTERNAL_REDTEAM_SIGNER_SHA256"\n    )',
        "    trusted = set()",
        (
            "apps/api/tests/test_ci_production_evidence_plumbing.py::"
            "test_redteam_validator_uses_protected_runtime_trust_without_source_mutation",
        ),
    ),
    Mutant(
        "M248_PRODUCTION_ASSURANCE_RUNTIME_TRUST_DISCONNECTED",
        "scripts/verify_production_assurance.py",
        '    trusted = trusted_fingerprints(\n        ROOT / "config/assurance/trusted-assurance-signers.json",\n        "production_assurance_ed25519_public_key_sha256",\n        "KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256",\n    )',
        "    trusted = set()",
        (
            "apps/api/tests/test_production_promotion_plumbing.py::"
            "test_production_assurance_verifier_accepts_runtime_trust_only_through_shared_guard",
        ),
    ),
    Mutant(
        "M249_RELEASE_RUNTIME_TRUST_IGNORED",
        "scripts/release_attestation.py",
        'trusted = (\n        trusted_fingerprints(trust_config or Path("/nonexistent"), trust_field, trust_env)\n        if trust_env\n        else _trusted(trust_config, trust_field)\n    )',
        "trusted = _trusted(trust_config, trust_field)",
        (
            "apps/api/tests/test_production_promotion_plumbing.py::"
            "test_release_attestation_can_use_protected_runtime_trust",
        ),
    ),
    Mutant(
        "M250_EXTERNAL_REDTEAM_COVERAGE_BYPASSED",
        "apps/api/src/korpus/application/external_redteam.py",
        '        "required_attack_families_covered": bool(required) and required.issubset(covered),',
        '        "required_attack_families_covered": True,',
        (
            "apps/api/tests/test_external_redteam_admissibility.py::"
            "test_declared_pass_cannot_hide_missing_attack_family",
        ),
    ),
    Mutant(
        "M251_EXTERNAL_REDTEAM_BLOCKING_FINDING_ACCEPTED",
        "apps/api/src/korpus/application/external_redteam.py",
        "        if severity in blocking and status not in blocking_allowed:",
        "        if False:",
        (
            "apps/api/tests/test_external_redteam_admissibility.py::"
            "test_blocking_finding_must_be_verified_fixed_not_merely_risk_accepted",
        ),
    ),
    Mutant(
        "M252_EXTERNAL_REDTEAM_PREREGISTRATION_BYPASSED",
        "scripts/validate_external_redteam_evidence.py",
        '        "preregistered": report.get("preregistration_sha256")\n        == hashlib.sha256(PROFILE.read_bytes()).hexdigest(),',
        '        "preregistered": True,',
        (
            "apps/api/tests/test_external_redteam_admissibility.py::"
            "test_trusted_signature_cannot_bypass_wrong_preregistration",
        ),
    ),
    Mutant(
        "M253_EXTERNAL_REDTEAM_INDEPENDENCE_BYPASSED",
        "scripts/validate_external_redteam_evidence.py",
        '        "independent_class": report.get("evidence_class") == "EXTERNAL_INDEPENDENT",',
        '        "independent_class": True,',
        (
            "apps/api/tests/test_external_redteam_admissibility.py::"
            "test_signed_internal_report_cannot_claim_external_independence",
        ),
    ),
    Mutant(
        "M254_EXTERNAL_REDTEAM_TRUST_BYPASSED",
        "scripts/validate_external_redteam_evidence.py",
        '"trusted_signer": signed.trusted_signer,',
        '"trusted_signer": True,',
        (
            "apps/api/tests/test_external_redteam_admissibility.py::"
            "test_valid_signature_without_preadmitted_trust_root_is_rejected",
        ),
    ),
    Mutant(
        "M255_TEVV_OBSERVATION_LEDGER_BYPASSED",
        "apps/api/src/korpus/application/tevv_evidence.py",
        '        "observation_ledger_structured": observations_ok,',
        '        "observation_ledger_structured": True,',
        (
            "apps/api/tests/test_tevv_attestation_boundary.py::"
            "test_trusted_aggregate_only_tevv_summary_cannot_replace_case_ledger",
        ),
    ),
    Mutant(
        "M256_TEVV_ATTACK_COVERAGE_BYPASSED",
        "apps/api/src/korpus/application/tevv_evidence.py",
        '        "required_attack_families_covered": required.issubset(set(metrics["attack_families"])),',
        '        "required_attack_families_covered": True,',
        (
            "apps/api/tests/test_tevv_attestation_boundary.py::"
            "test_trusted_tevv_ledger_must_cover_required_attack_families",
        ),
    ),
    Mutant(
        "M257_TEVV_DECLARED_AGGREGATE_CONFLICT_IGNORED",
        "apps/api/src/korpus/application/tevv_evidence.py",
        '        "declared_aggregates_consistent": _declared_consistent(evidence, metrics),',
        '        "declared_aggregates_consistent": True,',
        (
            "apps/api/tests/test_tevv_attestation_boundary.py::"
            "test_trusted_tevv_summary_cannot_hide_ledger_leakage_failure",
        ),
    ),
    Mutant(
        "M258_TEVV_LEAKAGE_LEDGER_IGNORED",
        "scripts/run_tevv_production_gate.py",
        '        "leakage": metrics["leakage_failures"] <= policy["maximum_leakage_failures"],',
        '        "leakage": evidence.get("leakage_failures", 0) <= policy["maximum_leakage_failures"],',
        (
            "apps/api/tests/test_tevv_attestation_boundary.py::"
            "test_trusted_tevv_summary_cannot_hide_ledger_leakage_failure",
        ),
    ),
    Mutant(
        "M259_TEVV_NULL_LEDGER_IGNORED",
        "scripts/run_tevv_production_gate.py",
        '        "null_false_accepts": metrics["null_control_false_accepts"]\n        <= policy["maximum_null_control_false_accepts"],',
        '        "null_false_accepts": evidence.get("null_control_false_accepts", 0)\n        <= policy["maximum_null_control_false_accepts"],',
        (
            "apps/api/tests/test_tevv_attestation_boundary.py::"
            "test_trusted_tevv_summary_cannot_hide_null_false_accept",
        ),
    ),
    Mutant(
        "M260_TEVV_DUPLICATE_OBSERVATION_IDS_ACCEPTED",
        "apps/api/src/korpus/application/tevv_evidence.py",
        '        "observation_ids_unique": len(observation_ids) == len(set(observation_ids)),',
        '        "observation_ids_unique": True,',
        (
            "apps/api/tests/test_tevv_attestation_boundary.py::"
            "test_trusted_tevv_duplicate_observation_ids_fail_closed",
        ),
    ),
    Mutant(
        "M261_TEVV_EVIDENCE_SCHEMA_BYPASSED",
        "scripts/run_tevv_production_gate.py",
        '        "evidence_schema": evidence.get("schema") == profile["evidence_schema"],',
        '        "evidence_schema": True,',
        (
            "apps/api/tests/test_tevv_attestation_boundary.py::"
            "test_trusted_tevv_wrong_evidence_schema_fails_closed",
        ),
    ),
    Mutant(
        "M262_PRODUCTION_ASSURANCE_RELATIVE_PATHS_BROKEN",
        "scripts/assemble_production_assurance.py",
        "    profile_path, gate_dir, out_path = (\n        args.profile.resolve(),\n        args.gate_dir.resolve(),\n        args.out.resolve(),\n    )",
        "    profile_path, gate_dir, out_path = args.profile, args.gate_dir, args.out",
        (
            "apps/api/tests/test_production_assurance_cli.py::"
            "test_production_assurance_cli_accepts_repo_relative_paths",
        ),
    ),
    Mutant(
        "M263_CONTAINER_IMAGE_SCAN_MARKER_IGNORED",
        "apps/api/src/korpus/application/supply_chain_scanners.py",
        "    return _scanner_marker_clean(scan, EXPECTED_CONTAINER_SCANNERS)",
        "    return True",
        (
            "apps/api/tests/test_supply_chain_evidence_boundary.py::test_container_scan_marker_requires_both_image_scans_exit_zero",
        ),
    ),
    Mutant(
        "M264_SUPPLY_MANIFEST_EXTRA_ARTIFACT_ACCEPTED",
        "apps/api/src/korpus/application/assurance_evidence.py",
        "        and set(declared) == set(artifacts)",
        "        and True",
        (
            "apps/api/tests/test_supply_chain_evidence_boundary.py::test_supply_chain_manifest_rejects_unverified_extra_artifact",
        ),
    ),
    Mutant(
        "M265_SCANNER_MARKER_COMMIT_REPLAY_ACCEPTED",
        "apps/api/src/korpus/application/supply_chain_scanners.py",
        '    return bool(expected_commit) and scan.get("commit_sha") == expected_commit',
        "    return True",
        (
            "apps/api/tests/test_supply_chain_evidence_boundary.py::test_scanner_marker_commit_must_match_current_pipeline_commit",
        ),
    ),
    Mutant(
        "M266_MISSION_HARD_FAILURE_COMPENSATED",
        "apps/api/src/korpus/application/mission_assurance_v2.py",
        "    if failures:",
        "    if False:",
        (
            "apps/api/tests/test_mission_assurance_v2.py::test_one_hard_failure_cannot_be_compensated_by_perfect_claim_accuracy",
        ),
    ),
    Mutant(
        "M267_MISSION_CONFIDENCE_BOUND_BYPASSED",
        "apps/api/src/korpus/application/mission_assurance_v2.py",
        "    if hard_interval.upper > maximum_hard_failure_rate_upper_95:",
        "    if False:",
        (
            "apps/api/tests/test_mission_assurance_v2.py::test_confidence_bound_alone_blocks_small_zero_failure_sample",
        ),
    ),
    Mutant(
        "M268_MISSION_INDEPENDENCE_BYPASSED",
        "apps/api/src/korpus/application/mission_assurance_v2.py",
        "    if not independent:",
        "    if False:",
        (
            "apps/api/tests/test_mission_assurance_v2.py::test_independence_alone_is_required_for_admission",
        ),
    ),
    Mutant(
        "M269_BROWSER_SESSION_COOKIE_PREFIX_BYPASSED",
        "apps/api/src/korpus/security/browser_cookie_policy.py",
        '    if not settings.browser_session_cookie.startswith("__Host-"):',
        "    if False:",
        (
            "apps/api/tests/test_controlled_configuration_refusals.py::test_a_controlled_deployment_refuses_each_weakening",
        ),
    ),
    Mutant(
        "M270_LOGOUT_CSRF_PAIR_BYPASSED",
        "apps/api/src/korpus/security/browser_cookie_policy.py",
        "    return bool(supplied and cookie and secrets.compare_digest(supplied, cookie))",
        "    return True",
        (
            "apps/api/tests/test_browser_oidc.py::test_logout_without_browser_csrf_pair_is_refused_even_without_session_cookie",
        ),
    ),
    Mutant(
        "M271_ZIP_ENTRY_BUDGET_BYPASSED",
        "scripts/zip_resource_policy.py",
        "    if len(infos) > MAX_ARCHIVE_ENTRIES:",
        "    if False:",
        (
            "apps/api/tests/test_package_zip_safety.py::test_entry_count_budget_refuses_before_structural_processing",
        ),
    ),
    Mutant(
        "M272_ZIP_COMPRESSION_RATIO_BYPASSED",
        "scripts/zip_resource_policy.py",
        "        elif info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:",
        "        elif False:",
        ("apps/api/tests/test_package_zip_safety.py::test_compression_ratio_budget_is_enforced",),
    ),
    Mutant(
        "M273_SAFE_EXTRACTION_ADMISSION_BYPASSED",
        "scripts/safe_archive_extract.py",
        "        if failures:",
        "        if False:",
        (
            "apps/api/tests/test_full_ssot_packager.py::test_safe_extractor_refuses_unsafe_archive_before_write",
        ),
    ),
    Mutant(
        "M274_NGINX_HSTS_INHERITANCE_BROKEN",
        "apps/web/nginx.cloudrun.conf",
        '    location = /api {\n      default_type application/json;\n      add_header X-Content-Type-Options nosniff always;\n      add_header X-Frame-Options DENY always;\n      add_header Referrer-Policy no-referrer always;\n      add_header Strict-Transport-Security "max-age=31536000" always;',
        "    location = /api {\n      default_type application/json;\n      add_header X-Content-Type-Options nosniff always;\n      add_header X-Frame-Options DENY always;\n      add_header Referrer-Policy no-referrer always;",
        (
            "apps/api/tests/test_nginx_security_headers.py::test_all_deployed_edges_persist_https_and_do_not_lose_headers_by_inheritance",
        ),
    ),
    Mutant(
        "M275_AUDIT_ANCHOR_EXTERNAL_HTTPS_BYPASSED",
        "apps/api/src/korpus/controlled_requirements.py",
        '            (s.audit_anchor_mode == "http" and is_external_https_url(s.audit_anchor_url))',
        '            (s.audit_anchor_mode == "http" and bool(s.audit_anchor_url))',
        (
            "apps/api/tests/test_controlled_configuration_refusals.py::test_a_controlled_deployment_refuses_each_weakening",
        ),
    ),
    Mutant(
        "M276_PEC_ADMISSION_THRESHOLD_BYPASSED",
        "apps/api/src/korpus/application/evidence_admission.py",
        "    return margins.minimum >= 0.0",
        "    return True",
        (
            "apps/api/tests/test_decision_sensitivity.py::test_boundary_margin_is_signed_distance_to_actual_retrieval_gate",
        ),
    ),
    Mutant(
        "M277_PEC_STRUCTURAL_ADMISSION_BYPASSED",
        "apps/api/src/korpus/application/evidence_admission.py",
        '    return item.version.review_state.value == "approved" and item.version.authority.is_normative',
        "    return True",
        (
            "apps/api/tests/test_decision_sensitivity.py::test_nonnormative_candidate_is_a_structural_block_not_fake_near_boundary",
        ),
    ),
    Mutant(
        "M278_PEC_BOUNDARY_DIVERGENCE_TOLERATED",
        "apps/api/src/korpus/application/pec_evidence_features.py",
        "    if boundary.retrieval_gate_passed != (eligible_count > 0):",
        "    if False:",
        (
            "apps/api/tests/test_decision_sensitivity.py::test_boundary_state_fails_closed_if_gate_and_feature_logic_diverge",
        ),
    ),
    Mutant(
        "M279_DGC_ADMISSIBLE_BASELINE_ESCALATED",
        "apps/api/src/korpus/application/pec_oracle_policy.py",
        "    if baseline.admissible():",
        "    if False:",
        (
            "apps/api/tests/test_pec_replay.py::test_oracle_never_buys_compute_when_baseline_is_already_admissible_even_if_noisy_latency_is_lower",
        ),
    ),
    Mutant(
        "M280_DGC_ORIGINAL_QUERY_BASELINE_OPTIONAL",
        "apps/api/src/korpus/application/pec_oracle_policy.py",
        '        return _decision(\n            query_id,\n            RetrievalAction.BASELINE,\n            "UNKNOWN",\n            "missing_original_query_stop_baseline",\n            [],\n        )',
        '        return _decision(query_id, RetrievalAction.PLAN_QUERY_VARIANTS, "PASS", "mutated", [])',
        ("apps/api/tests/test_pec_replay.py::test_oracle_requires_original_query_stop_baseline",),
    ),
    Mutant(
        "M281_PEC_ABLATION_QUALITY_REGRESSION_IGNORED",
        "apps/api/src/korpus/application/pec_ablation.py",
        '        "FAIL"\n        if safety_regressions or quality_regressions',
        '        "FAIL"\n        if safety_regressions',
        (
            "apps/api/tests/test_pec_protocol_gates.py::test_ablation_fails_before_efficiency_when_quality_regresses",
        ),
    ),
    Mutant(
        "M282_PEC_ABLATION_EFFICIENCY_EVIDENCE_BYPASSED",
        "apps/api/src/korpus/application/pec_ablation.py",
        '        else "PASS"\n        if supported_improvement',
        '        else "PASS"\n        if True',
        (
            "apps/api/tests/test_pec_protocol_gates.py::test_ablation_without_supported_efficiency_gain_remains_unknown",
        ),
    ),
    Mutant(
        "M283_PEC_METAMORPHIC_RISK_WEAKENING_IGNORED",
        "apps/api/src/korpus/application/pec_metamorphic_rules.py",
        "    elif transformed_risk < base_risk:",
        "    elif False:",
        (
            "apps/api/tests/test_pec_protocol_gates.py::test_metamorphic_invariant_kills_risk_weakening_and_source_unbinding",
        ),
    ),
    Mutant(
        "M284_PEC_PROMOTION_NONPASS_RECEIPT_IGNORED",
        "apps/api/src/korpus/application/pec_promotion.py",
        "    if nonpass:",
        "    if False:",
        (
            "apps/api/tests/test_pec_protocol_gates.py::test_promotion_refuses_any_nonpass_required_receipt",
        ),
    ),
    Mutant(
        "M285_DGC_DECISION_BOUNDARY_AUDIT_DROPPED",
        "apps/api/src/korpus/application/pec_trace_projection.py",
        '        "decision_boundary_distance": trace.decision_boundary_distance,',
        '        "decision_boundary_distance_mutated": trace.decision_boundary_distance,',
        (
            "apps/api/tests/test_pec_integration.py::test_controller_trace_reaches_completed_answer_audit",
        ),
    ),
    Mutant(
        "M286_PEC_CONTEXTUAL_EVIDENCE_MUTATION_IGNORED",
        "apps/api/src/korpus/application/pec_contextual_benchmark.py",
        "        if not evidence_unchanged:",
        "        if False:",
        (
            "apps/api/tests/test_pec_contextual_benchmark.py::test_contextual_benchmark_refuses_evidence_mutation",
        ),
    ),
    Mutant(
        "M287_PEC_TERMINAL_ABSTAIN_BYPASSED",
        "apps/api/src/korpus/application/answer_retrieval_gate.py",
        "    if early_abstain:",
        "    if False:",
        (
            "apps/api/tests/test_pec_integration.py::test_controller_abstain_is_terminal_even_when_first_pass_has_eligible_evidence",
        ),
    ),
    Mutant(
        "M288_PEC_ORIGINAL_QUERY_REPEATED_ON_ESCALATION",
        "apps/api/src/korpus/application/pec_retrieval.py",
        "    searches = plan.searches if include_asked else plan.variants",
        "    searches = plan.searches",
        (
            "apps/api/tests/test_pec_integration.py::test_planner_escalation_does_not_repeat_original_lexical_search",
        ),
    ),
    Mutant(
        "M289_PEC_PROMOTION_CROSS_RUN_REPLAY_ACCEPTED",
        "apps/api/src/korpus/application/pec_promotion_bindings.py",
        '        ("oracle", "replay_sha256", receipt_file_sha256.get("counterfactual_replay", "")),',
        '        ("oracle", "replay_sha256", str(receipts.get("oracle", {}).get("replay_sha256", ""))),',
        (
            "apps/api/tests/test_pec_protocol_gates.py::test_promotion_rejects_green_but_cross_run_evidence_chain",
        ),
    ),
    Mutant(
        "M290_PEC_CONTEXTUAL_CANDIDATE_RECOVERY_DISABLED",
        "apps/api/src/korpus/infrastructure/repository_search.py",
        "    if len(baseline) >= candidate_limit or not corpora or not terms:",
        "    if True:",
        (
            "apps/api/tests/test_search_index.py::test_contextual_candidate_fill_recovers_title_vocabulary_without_mutating_evidence",
        ),
    ),
    Mutant(
        "M291_PEC_CONTROLLED_CONTEXTUAL_GOVERNANCE_BYPASSED",
        "apps/api/src/korpus/pec_config_policy.py",
        "        if settings.contextual_retrieval_enabled and controlled:",
        "        if False:",
        (
            "apps/api/tests/test_pec_act_hardening.py::test_controlled_contextual_retrieval_cannot_run_outside_pec_governance",
        ),
    ),
    Mutant(
        "M292_PEC_REPLAY_STRING_BOOLEAN_ACCEPTED",
        "scripts/pec_replay_validation.py",
        "        if field in observation and not isinstance(observation.get(field), bool):",
        "        if False:",
        (
            "apps/api/tests/test_pec_act_hardening.py::test_replay_rejects_string_booleans_in_observed_outcomes",
        ),
    ),
    Mutant(
        "M293_PEC_EXPORT_CROSS_RUN_TRAINING_ACCEPTED",
        "scripts/pec_controller_export_impl.py",
        '        ("training.dataset_sha256", training.get("dataset_sha256"), dataset_sha256),',
        '        ("training.dataset_sha256", dataset_sha256, dataset_sha256),',
        (
            "apps/api/tests/test_pec_cli_paths.py::test_controller_export_refuses_cross_run_training_binding",
        ),
    ),
    Mutant(
        "M294_PEC_GROUPED_VALIDATION_SPLITS_SOURCE_LINEAGE",
        "apps/api/src/korpus/application/pec_training_validation.py",
        "        (\n            [row for row in data if buckets[row.group_id] != index],\n            [row for row in data if buckets[row.group_id] == index],\n        )",
        "        (\n            [row for row in data if _bucket(row.query_id, folds) != index],\n            [row for row in data if _bucket(row.query_id, folds) == index],\n        )",
        (
            "apps/api/tests/test_pec_research.py::test_nested_group_validation_is_outer_group_disjoint",
        ),
    ),
    Mutant(
        "M295_PEC_CONDITIONAL_RISK_UNDERPOWERED_ADMITTED",
        "apps/api/src/korpus/application/pec_research.py",
        "        is_admitted = len(values) >= minimum_samples and upper <= risk_limit",
        "        is_admitted = len(values) >= minimum_samples or upper <= risk_limit",
        (
            "apps/api/tests/test_pec_research.py::test_conditional_risk_underpowered_stratum_falls_back",
        ),
    ),
    Mutant(
        "M296_PEC_REPLAY_PRIORITY_INVERTS_ACCEPTED_ERROR",
        "apps/api/src/korpus/application/pec_replay.py",
        "        0 if flags[1] else 1,",
        "        1 if flags[1] else 0,",
        ("apps/api/tests/test_pec_research.py::test_replay_priority_enriches_explicit_failures",),
    ),
    Mutant(
        "M297_PEC_PRODUCTION_JUDGMENT_PROVENANCE_BYPASSED",
        "apps/api/src/korpus/application/pec_research.py",
        '        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):',
        "        if False:",
        (
            "apps/api/tests/test_pec_research.py::test_production_judgment_requires_bound_provenance",
        ),
    ),
    Mutant(
        "M298_PEC_INFORMATION_GAIN_SCALAR_UTILITY_INTRODUCED",
        "apps/api/src/korpus/application/pec_research.py",
        '                "retrieval_quality_deltas": deltas,',
        '                "retrieval_quality_deltas": deltas, "utility": 0.0,',
        (
            "apps/api/tests/test_pec_research.py::test_information_gain_is_vector_not_weighted_scalar",
        ),
    ),
    Mutant(
        "M299_PEC_SYNTHETIC_RESEARCH_GRANTED_PRODUCTION_AUTHORITY",
        "apps/api/src/korpus/application/pec_research.py",
        '    authority = validity.get("status") == "PASS"',
        "    authority = True",
        (
            "apps/api/tests/test_pec_research.py::test_research_status_refuses_non_production_authority",
        ),
    ),
    Mutant(
        "M300_PEC_NESTED_SELECTION_SEES_OUTER_VALIDATION",
        "apps/api/src/korpus/application/pec_training_validation.py",
        "            depth, min_leaf, inner = select_hyperparameters(outer_train)",
        "            depth, min_leaf, inner = select_hyperparameters(data)",
        ("apps/api/tests/test_pec_research.py::test_nested_selection_never_sees_outer_validation",),
    ),
    Mutant(
        "M301_PEC_PRODUCTION_ENVIRONMENT_BYPASSED",
        "apps/api/src/korpus/application/pec_revision_binding.py",
        '        if environment != "PRODUCTION":',
        "        if False:",
        (
            "apps/api/tests/test_pec_revision_binding_v097.py::test_revision_binding_rejects_nonproduction_environment",
        ),
    ),
    Mutant(
        "M302_PEC_AUDIT_REVISION_BINDING_BYPASSED",
        "apps/api/src/korpus/application/pec_audit_trace.py",
        '        if str(row.get("revision", "")) != binding.revision:',
        "        if False:",
        ("apps/api/tests/test_pec_audit_trace_v097.py::test_audit_trace_rejects_revision_drift",),
    ),
    Mutant(
        "M303_PEC_COHORT_MISSING_CASE_ACCEPTED",
        "apps/api/src/korpus/application/pec_cohort.py",
        "    complete = not missing and not unexpected and not duplicates and len(observed) == len(expected)",
        "    complete = not unexpected and not duplicates and len(observed) <= len(expected)",
        ("apps/api/tests/test_pec_cohort_v097.py::test_cohort_rejects_cherry_picked_missing_case",),
    ),
    Mutant(
        "M304_PEC_MODEL_SELF_JUDGMENT_ACCEPTED",
        "apps/api/src/korpus/application/pec_human_judgment.py",
        "        elif model_self_judgment:",
        "        elif False:",
        (
            "apps/api/tests/test_pec_human_judgment_v097.py::test_model_self_judgment_is_never_authoritative",
        ),
    ),
    Mutant(
        "M305_PEC_HUMAN_JUDGMENT_REVISION_DRIFT_ACCEPTED",
        "apps/api/src/korpus/application/pec_human_judgment.py",
        '        if str(row.get("revision", "")) != binding.revision:',
        "        if False:",
        (
            "apps/api/tests/test_pec_human_judgment_v097.py::test_human_judgment_rejects_revision_drift",
        ),
    ),
    Mutant(
        "M306_PEC_CANARY_REVISION_DRIFT_ACCEPTED",
        "apps/api/src/korpus/application/pec_canary_admission.py",
        '    if str(receipt.get("cloud_run_revision", "")) != cloud_run_revision:',
        "    if False:",
        (
            "apps/api/tests/test_pec_canary_admission_v097.py::test_canary_rejects_revision_mismatch",
        ),
    ),
    Mutant(
        "M307_PEC_CANARY_UNDERPOWERED_SAMPLE_ACCEPTED",
        "apps/api/src/korpus/application/pec_canary_admission.py",
        "    if isinstance(samples, bool) or not isinstance(samples, int) or samples < minimum_samples:",
        "    if False:",
        (
            "apps/api/tests/test_pec_canary_admission_v097.py::test_canary_rejects_underpowered_sample",
        ),
    ),
    Mutant(
        "M308_PEC_TRAINING_DATASET_DRIFT_ACCEPTED",
        "apps/api/src/korpus/application/pec_training_lineage.py",
        '        "dataset_sha256": str(receipt.get("dataset_sha256", "")) == dataset_sha256,',
        '        "dataset_sha256": True,',
        (
            "apps/api/tests/test_pec_training_lineage_v097.py::test_training_lineage_rejects_dataset_drift",
        ),
    ),
    Mutant(
        "M309_PEC_EVIDENCE_RECEIPT_RELEASE_DRIFT_ACCEPTED",
        "apps/api/src/korpus/application/pec_evidence_receipt.py",
        '    if str(payload.get("release", "")) != release:',
        "    if False:",
        (
            "apps/api/tests/test_pec_evidence_receipt_v097.py::test_evidence_receipt_rejects_release_drift",
        ),
    ),
    Mutant(
        "M310_PEC_LOCAL_SELF_ATTESTATION_ACCEPTED",
        "apps/api/src/korpus/application/pec_hosted_evidence.py",
        '        "not_local_self_attested": receipt.get("local_self_attested") is not True,',
        '        "not_local_self_attested": True,',
        (
            "apps/api/tests/test_pec_hosted_evidence_v097.py::test_hosted_evidence_rejects_local_self_attestation",
        ),
    ),
    Mutant(
        "M311_PEC_UNTRUSTED_EXTERNAL_SIGNER_ACCEPTED",
        "apps/api/src/korpus/application/pec_external_assurance.py",
        '        "trusted_signer": str(receipt.get("signer_fingerprint", "")) in trusted,',
        '        "trusted_signer": True,',
        (
            "apps/api/tests/test_pec_external_assurance_v097.py::test_external_assurance_rejects_untrusted_signer",
        ),
    ),
    Mutant(
        "M312_SLSA_ARTIFACT_SUBJECT_MUTATION_ACCEPTED",
        "apps/api/src/korpus/application/supply_chain_attestation.py",
        '    return (\n        item.get("name") == artifact_name\n        and isinstance(digest, Mapping)\n        and digest.get("sha256") == hashlib.sha256(artifact_bytes).hexdigest()\n    )',
        '    return item.get("name") == artifact_name and isinstance(digest, Mapping)',
        (
            "apps/api/tests/test_supply_chain_attestation_v097.py::test_in_toto_subject_rejects_artifact_mutation",
        ),
    ),
    # --- doctrine catalog provenance rules 9-14 (scripts/validate_doctrine_catalog.py) ----
    # Added 2026-08-29. The catalogue carried 349 mutants and none of them touched the rules
    # that decide whether a doctrine source may be staged at all: every one of the 73 tests
    # in test_doctrine_catalog.py was a negative control nobody had falsified.
    Mutant(
        "M313_CATALOG_EVIDENCE_FLOOR_DISABLED",
        "scripts/validate_doctrine_catalog.py",
        "        if actual < minimum:",
        "        if False:",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_deleting_the_evidence_is_refused_by_the_floor",
        ),
    ),
    Mutant(
        # The ratchet's off-by-one: losing exactly one probe or one anchor still passes.
        "M314_CATALOG_EVIDENCE_FLOOR_TOLERATES_ONE_LOSS",
        "scripts/validate_doctrine_catalog.py",
        "        if actual < minimum:",
        "        if actual < minimum - 1:",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_losing_exactly_one_anchor_is_refused_by_the_floor",
        ),
    ),
    Mutant(
        # Kills only while some count sits exactly on its floor (integrity_anchored == 12 on
        # 2026-08-29). A floor with slack under every key would let this survive.
        "M315_CATALOG_EVIDENCE_FLOOR_REFUSES_ITS_OWN_MINIMUM",
        "scripts/validate_doctrine_catalog.py",
        "        if actual < minimum:",
        "        if actual <= minimum:",
        ("apps/api/tests/test_doctrine_catalog.py::test_the_real_catalog_passes",),
    ),
    Mutant(
        # The guard reading what it guards: compare the floor with itself and it always holds.
        "M316_CATALOG_FLOOR_COMPARES_ITSELF_NOT_THE_COUNT",
        "scripts/validate_doctrine_catalog.py",
        "        actual = summary[key]  # type: ignore[literal-required]\n        if actual < minimum:",
        "        actual = minimum\n        if actual < minimum:",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_deleting_the_evidence_is_refused_by_the_floor",
        ),
    ),
    Mutant(
        "M317_CATALOG_NO_HOST_IS_PROBEABLE",
        "scripts/validate_doctrine_catalog.py",
        'PROBEABLE_HOSTS = ("zakon.rada.gov.ua",)',
        "PROBEABLE_HOSTS: tuple[str, ...] = ()",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_a_probeable_source_without_a_probe_is_refused",
        ),
    ),
    Mutant(
        "M318_CATALOG_NO_HOST_IS_UNDATED",
        "scripts/validate_doctrine_catalog.py",
        'UNDATED_HOSTS = ("mod.gov.ua",)',
        "UNDATED_HOSTS: tuple[str, ...] = ()",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_an_undated_ministry_page_without_an_anchor_is_refused",
        ),
    ),
    Mutant(
        "M319_CATALOG_MANDATORY_EVIDENCE_RULE_RETURNS_NOTHING",
        "scripts/validate_doctrine_catalog.py",
        '    identifier = str(entry.get("id", "<no id>"))\n    uri = str(entry.get("source_uri", ""))',
        '    return []\n    identifier = str(entry.get("id", "<no id>"))\n    uri = str(entry.get("source_uri", ""))',
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_a_probeable_source_without_a_probe_is_refused",
        ),
    ),
    Mutant(
        # Rule 14 per-entry is exercised by calling it directly. This asks whether the gate
        # calls it at all.
        "M320_CATALOG_MANDATORY_EVIDENCE_UNWIRED_FROM_THE_GATE",
        "scripts/validate_doctrine_catalog.py",
        "        problems.extend(_entry_problems(entry))\n        problems.extend(_mandatory_evidence_problems(entry))",
        "        problems.extend(_entry_problems(entry))",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_the_gate_entry_point_applies_the_mandatory_evidence_rule",
        ),
    ),
    Mutant(
        # Same question for rules 1-13: every negative control calls _entry_problems itself.
        "M321_CATALOG_ENTRY_RULES_UNWIRED_FROM_THE_GATE",
        "scripts/validate_doctrine_catalog.py",
        "        problems.extend(_entry_problems(entry))\n        problems.extend(_mandatory_evidence_problems(entry))",
        "        problems.extend(_mandatory_evidence_problems(entry))",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_the_gate_entry_point_applies_the_per_entry_rules",
        ),
    ),
    Mutant(
        "M322_CATALOG_REPEALED_MARKER_READ_IN_THE_WRONG_CASE",
        "scripts/validate_doctrine_catalog.py",
        '    if status == "invalid" and ingestible:',
        '    if status == "INVALID" and ingestible:',
        ("apps/api/tests/test_doctrine_catalog.py::test_a_repealed_act_may_not_be_ingestible",),
    ),
    Mutant(
        # Rule 12 refuses a repealed act that is *ingestible*; a repealed act kept as history
        # is legitimate. Dropping the conjunct blocks the legitimate case.
        "M323_CATALOG_REPEALED_ACT_BLOCKED_EVEN_WHEN_NOT_INGESTIBLE",
        "scripts/validate_doctrine_catalog.py",
        '    if status == "invalid" and ingestible:',
        '    if status == "invalid":',
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_a_repealed_act_kept_for_reference_but_blocked_is_allowed",
        ),
    ),
    Mutant(
        "M324_CATALOG_LEGAL_STATUS_VOCABULARY_WIDENED",
        "scripts/validate_doctrine_catalog.py",
        'LEGAL_STATUSES = frozenset({"valid", "invalid", "unknown"})',
        'LEGAL_STATUSES = frozenset({"valid", "invalid", "unknown", "INVALID", ""})',
        ("apps/api/tests/test_doctrine_catalog.py::test_an_unrecognised_legal_status_is_refused",),
    ),
    Mutant(
        "M325_CATALOG_UNRECOGNISED_LEGAL_STATUS_ACCEPTED",
        "scripts/validate_doctrine_catalog.py",
        "    if not isinstance(status, str) or status not in LEGAL_STATUSES:",
        "    if not isinstance(status, str):",
        ("apps/api/tests/test_doctrine_catalog.py::test_an_unrecognised_legal_status_is_refused",),
    ),
    Mutant(
        "M326_CATALOG_ZIP_MEMBER_CHECK_REMOVED",
        "scripts/validate_doctrine_catalog.py",
        'ZIP_MEMBER = {".docx": "word/document.xml", ".xlsx": "xl/workbook.xml"}',
        "ZIP_MEMBER: dict[str, str] = {}",
        ("apps/api/tests/test_doctrine_catalog.py::test_a_jar_renamed_docx_is_refused",),
    ),
    Mutant(
        "M327_CATALOG_TEXTUAL_CAPTURE_FLOOR_REMOVED",
        "scripts/validate_doctrine_catalog.py",
        "MIN_TEXTUAL_WORDS = 120",
        "MIN_TEXTUAL_WORDS = 0",
        (
            "apps/api/tests/test_doctrine_catalog.py::test_a_404_page_above_the_byte_floor_is_still_refused",
        ),
    ),
    Mutant(
        "M328_CATALOG_FILE_SIGNATURE_COMPARISON_INVERTED",
        "scripts/validate_doctrine_catalog.py",
        "        if prefix != expected:",
        "        if prefix == expected:",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_a_captured_error_page_under_a_docx_name_is_refused",
        ),
    ),
    Mutant(
        "M329_CATALOG_EXTRACTOR_HONESTY_CHECK_REMOVED",
        "scripts/validate_doctrine_catalog.py",
        '        if bool(anchor.get("extractor_supports_format")) is not readable:',
        "        if False:",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_an_attachment_claiming_a_format_the_extractor_cannot_read_is_refused",
        ),
    ),
    Mutant(
        "M330_CATALOG_UNCAPTURED_REQUIRED_ATTACHMENT_ACCEPTED",
        "scripts/validate_doctrine_catalog.py",
        "        if uri not in captured:",
        "        if False:",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_a_required_attachment_nobody_captured_is_refused",
        ),
    ),
    Mutant(
        "M331_CATALOG_ONE_MEASURED_VARIANT_IS_ENOUGH",
        "scripts/validate_doctrine_catalog.py",
        '    missing = [name for name in ("card", "print") if name not in measured]',
        "    missing: list[str] = []",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_dropping_the_richer_variant_no_longer_hides_the_thinner_one",
        ),
    ),
    Mutant(
        "M332_CATALOG_THINNER_VARIANT_ACCEPTED",
        "scripts/validate_doctrine_catalog.py",
        "    if measured[chosen] < measured[richest]:",
        "    if False:",
        ("apps/api/tests/test_doctrine_catalog.py::test_choosing_the_thinner_variant_is_refused",),
    ),
    Mutant(
        "M333_CATALOG_RICHEST_VARIANT_REFUSES_ITSELF",
        "scripts/validate_doctrine_catalog.py",
        "    if measured[chosen] < measured[richest]:",
        "    if measured[chosen] <= measured[richest]:",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_a_probed_entry_pointing_at_its_richest_variant_passes",
        ),
    ),
    Mutant(
        "M334_CATALOG_SOURCE_URI_PROBE_PARITY_DROPPED",
        "scripts/validate_doctrine_catalog.py",
        "    elif source_uri and source_uri != chosen_uri:",
        "    elif False:",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_pointing_at_the_card_after_the_probe_found_the_text_elsewhere_is_refused",
        ),
    ),
    Mutant(
        "M335_CATALOG_ANCHOR_MAY_BE_ANY_FILE_IN_THE_TREE",
        "scripts/validate_doctrine_catalog.py",
        "        target.relative_to(CAPTURE_ROOT)",
        "        target.relative_to(ROOT)",
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_an_anchor_on_an_arbitrary_repository_file_is_refused",
        ),
    ),
    Mutant(
        "M336_CATALOG_ANCHOR_DIGEST_COMPARISON_INVERTED",
        "scripts/validate_doctrine_catalog.py",
        "    if actual != declared:",
        "    if actual == declared:",
        ("apps/api/tests/test_doctrine_catalog.py::test_a_changed_page_snapshot_is_caught",),
    ),
    Mutant(
        "M337_CATALOG_PROBE_NEVER_GOES_STALE",
        "scripts/validate_doctrine_catalog.py",
        "    if age > PROBE_MAX_AGE_DAYS:",
        "    if age > 100000:",
        ("apps/api/tests/test_doctrine_catalog.py::test_a_stale_probe_is_refused",),
    ),
    Mutant(
        "M338_CATALOG_PROBE_DATED_IN_THE_FUTURE_ACCEPTED",
        "scripts/validate_doctrine_catalog.py",
        "    if age < 0:",
        "    if False:",
        ("apps/api/tests/test_doctrine_catalog.py::test_a_probe_dated_in_the_future_is_refused",),
    ),
    Mutant(
        # A probe with no date is not stale, ever: the freshness rule reads a field nothing
        # requires to be there.
        "M339_CATALOG_UNDATED_PROBE_ACCEPTED",
        "scripts/validate_doctrine_catalog.py",
        "    if not isinstance(probed_on, str):",
        "    if False:",
        ("apps/api/tests/test_doctrine_catalog.py::test_a_probe_with_no_date_at_all_is_refused",),
    ),
    Mutant(
        # The floor is only as honest as the counts it reads.
        "M340_CATALOG_PROBE_COUNT_INFLATED_TO_EVERY_SOURCE",
        "scripts/validate_doctrine_catalog.py",
        '        "content_probed": len([e for e in dicts if e.get("content_probe")]),',
        '        "content_probed": len(dicts),',
        (
            "apps/api/tests/test_doctrine_catalog.py::"
            "test_every_probed_source_in_the_catalog_points_at_its_measured_content",
        ),
    ),
    Mutant(
        # `"lines": "999999"` lifted the ratchet for a module and reported PASS.
        "M341_MODULE_BUDGET_STRING_CEILING_ACCEPTED",
        "scripts/check_module_budget.py",
        "    return value if isinstance(value, int) and not isinstance(value, bool) else fallback",
        "    return value if not isinstance(value, bool) else fallback",
        (
            "apps/api/tests/test_gate_parity.py::"
            "test_a_string_line_ceiling_does_not_lift_the_ratchet",
        ),
    ),
    Mutant(
        # External production proof unbound by a later commit must fail the gate, not be
        # printed beside a zero exit.
        "M342_PRODUCTION_PREDICATE_FLOOR_DISABLED",
        "scripts/verify_production_hard_predicates.py",
        '    if payload["production_satisfied"] < floor:',
        "    if False:",
        (
            "apps/api/tests/test_gate_parity.py::"
            "test_the_hard_predicate_floor_fails_the_gate_when_external_proof_is_lost",
        ),
    ),
    # ── Публічна поверхня. Отрута по ПОВЕДІНЦІ правила, не по його оформленню:
    # мутант, що ламає лише текст повідомлення, вижив би й не довів нічого про охорону.
    Mutant(
        "M399_CONSOLE_CLOSURE_FOLLOWS_NAVIGATION",
        "scripts/public_operator_surface.py",
        r"""re.compile(r'<script[^>]*\ssrc="(?P<target>/?[A-Za-z0-9_.\-]+\.js)"'),""",
        r"""re.compile(r'(?:src|href)="(?P<target>/?[A-Za-z0-9_.\-]+\.(?:js|css|html))"'),""",
        (
            "apps/api/tests/test_public_surface.py::test_navigation_link_to_the_console_does_not_make_the_console_public",
            "apps/api/tests/test_public_surface.py::test_operator_surface_is_the_whole_console_not_three_filenames",
        ),
        full_copy=True,
    ),
    Mutant(
        "M400_READER_ESSENTIAL_MAY_BE_WITHHELD",
        "scripts/public_operator_surface.py",
        "    if essential:",
        "    if False:",
        (
            "apps/api/tests/test_public_surface.py::test_rule_that_would_withhold_a_reader_essential_refuses",
        ),
        full_copy=True,
    ),
    Mutant(
        "M401_RECOVERY_LADDER_NEVER_CLIMBS",
        "scripts/public_health_controller.py",
        "            rung = min(int(attempts.get(component, 0)), len(ladder) - 1)",
        "            rung = 0",
        (
            "apps/api/tests/test_public_health_controller.py::test_second_attempt_at_one_outage_is_a_different_action",
        ),
        full_copy=True,
    ),
    Mutant(
        "M402_HEALTH_DOES_NOT_RESET_THE_RUNG",
        "scripts/public_health_controller.py",
        "        if health[component]:\n            attempts[component] = 0",
        "        if False:\n            attempts[component] = 0",
        (
            "apps/api/tests/test_public_health_controller.py::test_health_resets_the_rung_so_a_new_outage_starts_gently",
        ),
        full_copy=True,
    ),
    Mutant(
        "M403_RECOVERY_RUNS_ONLY_ITS_FIRST_COMMAND",
        "scripts/public_health_controller.py",
        "    for command in ACTION_COMMANDS[action]:",
        "    for command in ACTION_COMMANDS[action][:1]:",
        (
            "apps/api/tests/test_public_health_controller.py::test_execute_runs_the_whole_sequence_not_only_its_first_command",
        ),
        full_copy=True,
    ),
    Mutant(
        "M404_UNKNOWN_COUNTED_AS_PASS",
        "scripts/verify_public_surface.py",
        '    if "UNKNOWN" in verdicts:',
        "    if False:",
        ("apps/api/tests/test_public_surface.py::test_unknown_never_counts_as_pass",),
        full_copy=True,
    ),
    Mutant(
        "M405_INDEX_MASQUERADE_COUNTED_AS_CLOSED",
        "scripts/verify_public_surface.py",
        "    if not (leaked or masquerade):",
        "    if not leaked:",
        ("apps/api/tests/test_public_surface.py::test_gate_reddens_on_every_defect_separately",),
        full_copy=True,
    ),
    Mutant(
        "M406_UNAUTHENTICATED_401_COUNTED_AS_ROLE_REFUSAL",
        "scripts/verify_public_surface.py",
        "    unproven = sorted(route for route, code in direct.items() if code == 401)",
        "    unproven: list[str] = []",
        ("apps/api/tests/test_public_surface.py::test_gate_reddens_on_every_defect_separately",),
        full_copy=True,
    ),
    Mutant(
        "M407_OFF_LOOPBACK_ADDRESSES_IGNORED",
        "scripts/verify_public_surface.py",
        '        if entry.get("status") == 200 and entry.get("address") not in LOOPBACK',
        '        if entry.get("status") == 200 and entry.get("address") in LOOPBACK',
        ("apps/api/tests/test_public_surface.py::test_gate_reddens_on_every_defect_separately",),
        full_copy=True,
    ),
    Mutant(
        "M408_EXTERNAL_EGRESS_ACCEPTED_ON_PUBLIC_SURFACE",
        "scripts/verify_public_surface.py",
        '    if status["egress_posture"] == "external_allowed":',
        "    if False:",
        ("apps/api/tests/test_public_surface.py::test_gate_reddens_on_every_defect_separately",),
        full_copy=True,
    ),
    # Закриття як математичний об'єкт. Обидві отрути ламають ВЛАСТИВІСТЬ, не текст:
    # перша робить обхід одношаровим, друга — знімає віднімання читацького закриття.
    Mutant(
        "M420_TRAVERSAL_STOPS_AT_ONE_LEVEL",
        "scripts/public_operator_surface.py",
        '                pending.append(match.group("target").lstrip("./").lstrip("/"))',
        '                seen.add(match.group("target").lstrip("./").lstrip("/"))',
        (
            "apps/api/tests/test_public_surface.py::test_traversal_is_a_true_transitive_closure_over_every_small_graph",
            "apps/api/tests/test_public_surface.py::test_operator_surface_is_the_whole_console_not_three_filenames",
        ),
        full_copy=True,
    ),
    Mutant(
        "M421_READER_CLOSURE_NOT_SUBTRACTED",
        "scripts/public_operator_surface.py",
        "    withheld = _reachable(source, OPERATOR_ENTRY) - _reachable(source, READER_ENTRY)",
        "    withheld = _reachable(source, OPERATOR_ENTRY)",
        (
            "apps/api/tests/test_public_surface.py::test_a_reader_link_can_only_shrink_the_operator_surface",
            "apps/api/tests/test_public_surface.py::test_shared_module_stays_public_when_both_pages_load_it",
        ),
        full_copy=True,
    ),
    Mutant(
        "M422_BUDGET_NAMING_MATCHES_THE_PATH_NOT_THE_RAISE",
        "scripts/check_budget_raises_are_named.py",
        "            if k in previous and v > previous[k] and (k, v) not in named",
        "            if k in previous and v > previous[k] and not named",
        (
            "apps/api/tests/test_budget_raises_are_named.py"
            "::test_a_record_for_another_number_does_not_excuse_this_raise",
            "apps/api/tests/test_budget_raises_are_named.py"
            "::test_a_record_naming_another_ceiling_key_does_not_excuse_this_one",
        ),
        full_copy=True,
    ),
    Mutant(
        "M423_PUBLIC_DEPLOY_INVENTS_THE_EVIDENCE_KEY",
        "scripts/serve_public.sh",
        'export KORPUS_AUDIT_HMAC_KEY_FILE="$SECRET_DIR/audit-key.txt"',
        'export KORPUS_AUDIT_HMAC_KEY="${KORPUS_AUDIT_HMAC_KEY:-local-audit-key}"',
        (
            "apps/api/tests/test_public_deployment_script.py"
            "::test_the_public_deploy_does_not_invent_the_key_that_signs_the_evidence",
        ),
        full_copy=True,
    ),
    Mutant(
        "M424_A_QUOTE_THAT_IS_NOT_IN_ITS_SOURCE_COUNTS_AS_VERBATIM",
        "scripts/measure_corpus_integrity.py",
        "        if needle in source:",
        "        if True:",
        (
            "apps/api/tests/test_corpus_integrity.py::"
            "test_a_passage_that_is_not_a_verbatim_slice_of_its_source_is_not_credited",
        ),
        full_copy=True,
    ),
    Mutant(
        "M425_A_SPAN_ITS_SOURCE_DOES_NOT_HOLD_IS_CREDITED_AS_A_BOUNDARY",
        "scripts/measure_corpus_integrity.py",
        "            unlocatable += 1\n            continue\n        cursor = at + len(needle)",
        "            boundary += 1\n            continue\n        cursor = at + len(needle)",
        (
            "apps/api/tests/test_corpus_integrity.py::"
            "test_a_passage_whose_source_is_absent_is_counted_apart_not_credited",
        ),
        full_copy=True,
    ),
    Mutant(
        "M426_AN_EVENT_SIGNED_BY_ANOTHER_KEY_COUNTS_AS_ATTRIBUTED",
        "scripts/measure_audit_integrity.py",
        "        elif actual == named:",
        "        elif actual is not None:",
        (
            "apps/api/tests/test_audit_ledger_attribution.py::"
            "test_an_event_signed_by_another_held_key_is_misattributed_not_broken",
        ),
        full_copy=True,
    ),
    Mutant(
        "M427_AN_EVENT_NO_KEY_VERIFIES_IS_NOT_REPORTED",
        "scripts/measure_audit_integrity.py",
        "        if actual is None:\n            unverifiable += 1",
        "        if False:\n            unverifiable += 1",
        (
            "apps/api/tests/test_audit_ledger_attribution.py::"
            "test_an_event_no_offered_key_verifies_is_unverifiable_not_forgery",
        ),
        full_copy=True,
    ),
    Mutant(
        "M428_RELABELLING_PROCEEDS_OVER_AN_UNVERIFIABLE_LEDGER",
        "scripts/attribute_audit_keys.py",
        "        if not matches:\n            refusals.append(",
        "        if False:\n            refusals.append(",
        (
            "apps/api/tests/test_audit_ledger_attribution.py::"
            "test_an_unverifiable_event_stops_the_whole_relabelling",
        ),
        full_copy=True,
    ),
    Mutant(
        "M429_THE_ANCHOR_MAY_BE_ROLLED_BACK_BEHIND_THE_HEAD",
        "scripts/reissue_audit_anchor.py",
        "    if anchor_sequence > head_sequence:",
        "    if False:",
        (
            "apps/api/tests/test_audit_ledger_attribution.py::"
            "test_the_anchor_is_only_reissued_over_a_ledger_that_verifies_whole",
        ),
        full_copy=True,
    ),
    Mutant(
        "M430_A_LINK_IS_CONFIRMED_WITHOUT_READING_THE_SOURCE",
        "scripts/validate_derived_source_links.py",
        "        if len(candidate) == length and candidate in body:",
        "        if len(candidate) == length:",
        (
            "apps/api/tests/test_derived_source_links.py::"
            "test_a_head_the_named_source_does_not_carry_is_refused",
        ),
        full_copy=True,
    ),
    Mutant(
        "M431_AN_AMBIGUOUS_PARENT_IS_GUESSED_INSTEAD_OF_LEFT_ALONE",
        "scripts/relink_derived_articles.py",
        '        if len(found) > 1:\n            skipped["ambiguous"] += 1\n            continue',
        "        if len(found) > 1:\n            found = found[:1]",
        (
            "apps/api/tests/test_derived_source_links.py::"
            "test_a_head_two_statutes_both_carry_is_left_alone_rather_than_guessed",
        ),
        full_copy=True,
    ),
    Mutant(
        "M432_A_HOLE_IN_THE_COVERAGE_OF_THE_SOURCE_IS_NOT_REPORTED",
        "scripts/respan_from_source.py",
        "        if index and start > spans[index - 1][1]:",
        "        if False:",
        ("apps/api/tests/test_respan_from_source.py::test_a_hole_is_refused_rather_than_written",),
        full_copy=True,
    ),
    Mutant(
        "M433_THE_SPAN_CEILING_IS_NOT_ENFORCED",
        "scripts/respan_from_source.py",
        "        if end - start > limit:",
        "        if False:",
        (
            "apps/api/tests/test_respan_from_source.py::"
            "test_a_span_over_the_ceiling_is_refused_by_the_check_not_only_avoided_by_the_cutter",
        ),
        full_copy=True,
    ),
    # ── Покриття гейтами. Отрути ламають ОЗНАЧЕННЯ покриття, не його оформлення.
    Mutant(
        "M434_COVERAGE_IGNORES_SCRIPT_EQUIVALENCE",
        "scripts/verify_gate_closure.py",
        "        if used and used <= running:",
        "        if False:",
        (
            "apps/api/tests/test_gate_closure.py::test_a_target_whose_script_another_target_runs_is_not_a_gap",
        ),
        full_copy=True,
    ),
    Mutant(
        "M435_RECIPE_EDGES_ARE_NOT_REACHABILITY",
        "scripts/verify_gate_closure.py",
        "                for match in _RECURSIVE_MAKE.finditer(line):",
        '                for match in _RECURSIVE_MAKE.finditer(""):',
        ("apps/api/tests/test_gate_closure.py::test_recipe_edges_count_as_reachability",),
        full_copy=True,
    ),
    Mutant(
        "M436_A_DEAD_EXEMPTION_IS_TOLERATED",
        "scripts/verify_gate_closure.py",
        "    dead = sorted(t for t in named if t in covered)",
        "    dead: list[str] = []",
        (
            "apps/api/tests/test_gate_closure.py::test_an_exemption_for_something_already_enforced_reddens",
        ),
        full_copy=True,
    ),
    Mutant(
        "M437_A_GHOST_EXEMPTION_IS_TOLERATED",
        "scripts/verify_gate_closure.py",
        "    ghosts = sorted(t for t in named if t not in edges)",
        "    ghosts: list[str] = []",
        (
            "apps/api/tests/test_gate_closure.py::test_an_exemption_for_a_target_that_no_longer_exists_reddens",
        ),
        full_copy=True,
    ),
    Mutant(
        "M438_AN_UNREGISTERED_GAP_IS_TOLERATED",
        "scripts/verify_gate_closure.py",
        "    missing = sorted(t for t in targets if t not in covered and t not in named)",
        "    missing: list[str] = []",
        (
            "apps/api/tests/test_gate_closure.py::test_a_new_unwired_verification_target_reddens_on_the_real_makefile",
        ),
        full_copy=True,
    ),
    Mutant(
        "M439_AN_AMBIGUOUS_PARENT_IS_SETTLED_BY_GUESSING_THE_FIRST",
        "scripts/relink_derived_articles.py",
        "    return agreeing[0] if len(agreeing) == 1 else None",
        "    return agreeing[0] if agreeing else None",
        (
            "apps/api/tests/test_derived_source_links.py::"
            "test_a_number_matching_two_candidates_is_left_unsettled",
        ),
        full_copy=True,
    ),
    Mutant(
        "M440_A_PART_INDEX_IS_TRUSTED_AS_AN_ARTICLE_NUMBER",
        "scripts/relink_derived_articles.py",
        "    if not named or int(named.group(1)) < SMALLEST_TRUSTED_ARTICLE:",
        "    if not named:",
        (
            "apps/api/tests/test_derived_source_links.py::"
            "test_a_small_number_is_not_trusted_because_it_is_usually_a_part_index",
        ),
        full_copy=True,
    ),
    Mutant(
        "M454_RECONCILE_TAKES_ITS_TARGET_FROM_THE_SHARED_OUTBOX_AGAIN",
        "apps/api/src/korpus/infrastructure/repository.py",
        "                select(audit_heads.c.sequence, audit_heads.c.head_hash).where(\n"
        "                    audit_heads.c.singleton_id == 1\n"
        "                )",
        "                select(audit_anchor_outbox.c.sequence, audit_anchor_outbox.c.head_hash)\n"
        "                .where(audit_anchor_outbox.c.delivered_at.is_(None))\n"
        "                .order_by(audit_anchor_outbox.c.sequence.desc())\n"
        "                .limit(1)",
        (
            "apps/api/tests/test_anchor_delivery_backlog.py::"
            "test_an_anchor_behind_the_head_catches_up_even_with_an_empty_outbox",
        ),
    ),
    Mutant(
        "M455_THE_ANCHOR_GAP_IS_REPORTED_AS_THE_OUTBOX_LENGTH",
        "apps/api/src/korpus/infrastructure/observability.py",
        '            int(snapshot["anchor_gap_events"]),  # type: ignore[call-overload]',
        '            int(snapshot["pending_anchor_events"]),  # type: ignore[call-overload]',
        (
            "apps/api/tests/test_observability.py::"
            "test_readiness_maps_the_anchor_gap_and_not_the_queue_length",
        ),
    ),
    Mutant(
        "M516_THE_VERIFIER_WRITES_INTO_THE_EVIDENCE_IT_VERIFIES",
        "scripts/verify_regression_carry_forward.py",
        '    parser.add_argument("--out", type=Path, default=ROOT / "var/regression-carry-forward.json")',
        '    parser.add_argument("--out", type=Path, default=ROOT / "reports/release/v0.7.0/RCF.json")',
        (
            "apps/api/tests/test_regression_carry_forward.py::"
            "test_the_verifier_does_not_write_into_the_evidence_it_verifies",
        ),
        full_copy=True,
    ),
    Mutant(
        "M513_A_LIST_IS_READ_AS_A_NUMBER_WITHOUT_BEING_ASKED",
        "scripts/check_deployment_debt.py",
        '    if kind == "length":',
        "    if True:",
        (
            "apps/api/tests/test_deployment_debt.py::"
            "test_a_list_is_not_a_number_unless_the_entry_says_so",
        ),
        full_copy=True,
    ),
    Mutant(
        "M514_THE_LENGTH_OF_A_NON_LIST_IS_INVENTED",
        "scripts/check_deployment_debt.py",
        "        return len(node) if isinstance(node, list) else None",
        '        return len(node) if hasattr(node, "__len__") else None',
        (
            "apps/api/tests/test_deployment_debt.py::"
            "test_length_of_something_that_is_not_a_list_is_unknown",
        ),
        full_copy=True,
    ),
    Mutant(
        "M515_THE_ENTRY_KIND_IS_IGNORED_AND_EVERY_METRIC_IS_A_NUMBER",
        "scripts/check_deployment_debt.py",
        '        report, str(entry.get("metric", "")), str(entry.get("metric_kind", "number"))',
        '        report, str(entry.get("metric", ""))',
        (
            "apps/api/tests/test_deployment_debt.py::"
            "test_a_list_of_failures_is_measured_by_its_length",
        ),
        full_copy=True,
    ),
    Mutant(
        "M507_THE_SERVED_STORE_IS_NEVER_COMPARED_TO_WHAT_THE_UNIT_HANDS_OVER",
        "scripts/verify_evidence_stores.py",
        "    if served[0] != unit:",
        "    if False:",
        (
            "apps/api/tests/test_evidence_stores.py::"
            "test_the_served_store_is_the_one_the_unit_hands_the_service",
        ),
        full_copy=True,
    ),
    Mutant(
        "M508_A_STORE_NOBODY_NAMED_IS_NOT_REPORTED",
        "scripts/verify_evidence_stores.py",
        '    extra = sorted(set(observation["stores"]) - set(declared))',
        "    extra = []",
        ("apps/api/tests/test_evidence_stores.py::test_a_store_nobody_named_is_refused",),
        full_copy=True,
    ),
    Mutant(
        "M509_AN_OPTIONAL_STORE_THAT_IS_ABSENT_IS_CALLED_A_GHOST",
        "scripts/verify_evidence_stores.py",
        '        if path not in observation["stores"] and not entry.get("optional")',
        '        if path not in observation["stores"]',
        ("apps/api/tests/test_evidence_stores.py::test_an_optional_store_may_be_absent",),
        full_copy=True,
    ),
    Mutant(
        "M510_ANY_NUMBER_OF_SERVED_STORES_IS_ACCEPTED",
        "scripts/verify_evidence_stores.py",
        "    if len(served) == 1:",
        "    if len(served) >= 1:",
        ("apps/api/tests/test_evidence_stores.py::test_two_served_stores_are_refused",),
        full_copy=True,
    ),
    Mutant(
        "M511_THE_CONFIG_DEFAULT_MAY_QUIETLY_BE_THE_SERVED_CORPUS",
        "scripts/verify_evidence_stores.py",
        '    if entry.get("role") == "served":',
        "    if False:",
        (
            "apps/api/tests/test_evidence_stores.py::"
            "test_the_config_default_must_not_be_the_served_store",
        ),
        full_copy=True,
    ),
    Mutant(
        "M512_HALF_THE_SHAPE_IS_ENOUGH_TO_BE_AN_EVIDENCE_STORE",
        "scripts/verify_evidence_stores.py",
        "        if not set(SHAPE) <= names:",
        "        if not set(SHAPE) & names:",
        (
            "apps/api/tests/test_evidence_stores.py::"
            "test_only_both_tables_together_make_an_evidence_store",
        ),
        full_copy=True,
    ),
    Mutant(
        "M517_THE_PACKAGE_LANE_STOPS_CHECKING_THE_ARCHIVE_IT_SHIPS",
        "Makefile",
        '\tPYTHONPATH=apps/api/src:. $(PY) scripts/zip_safety.py "$$(cat dist/LATEST)"',
        "\t@true",
        (
            "apps/api/tests/test_gate_closure.py::"
            "test_the_packaging_lane_checks_the_archive_it_produces",
        ),
        full_copy=True,
    ),
    Mutant(
        "M518_THE_ARCHIVE_NAME_GETS_A_SECOND_SOURCE",
        "scripts/package_repository.sh",
        'printf \'%s\\n\' "dist/${name}.zip" > "dist/LATEST"',
        ": # ім'я більше не публікується",
        (
            "apps/api/tests/test_gate_closure.py::"
            "test_the_packaging_lane_checks_the_archive_it_produces",
        ),
        full_copy=True,
    ),
    Mutant(
        "M532_THE_CLASSIFIER_STOPS_SEEING_AXIS_AND_STORE_SHAPED_NAMES",
        "scripts/verify_gate_closure.py",
        '    r"|axes|stores|selftest"',
        '    r"|zzzz-nothing-matches-this"',
        (
            "apps/api/tests/test_gate_closure.py::"
            "test_the_classifier_sees_axis_and_store_shaped_names",
        ),
        full_copy=True,
    ),
    Mutant(
        "M533_A_TARGET_THAT_DOES_MORE_THAN_A_SELFTEST_IS_COVERED_FOR_FREE",
        "scripts/verify_gate_closure.py",
        '        if lines and all("--selftest" in line for line in lines):',
        '        if lines and any("--selftest" in line for line in lines):',
        (
            "apps/api/tests/test_gate_closure.py::"
            "test_a_target_that_does_more_than_a_selftest_is_not_covered_for_free",
        ),
        full_copy=True,
    ),
    Mutant(
        "M534_THE_SELFTEST_SHORTCUT_APPLIES_EVEN_WITHOUT_THE_SELFTEST_GATE",
        "scripts/verify_gate_closure.py",
        '    if "selftest-coverage" in covered:',
        "    if True:",
        (
            "apps/api/tests/test_gate_closure.py::"
            "test_the_selftest_shortcut_needs_the_selftest_gate_to_be_covered",
        ),
        full_copy=True,
    ),
    Mutant(
        "M535_AN_INSTALLED_UNIT_THAT_DIFFERS_FROM_THE_TREE_IS_ACCEPTED",
        "scripts/verify_installed_units.py",
        "        if mine == theirs:",
        "        if True:",
        (
            "apps/api/tests/test_installed_units.py::"
            "test_an_extra_directive_in_the_installed_unit_is_refused",
        ),
        full_copy=True,
    ),
    Mutant(
        "M536_A_COMMENT_IS_TREATED_AS_A_DIFFERENCE",
        "scripts/verify_installed_units.py",
        '        if line.strip() and not line.lstrip().startswith("#")',
        "        if line.strip()",
        ("apps/api/tests/test_installed_units.py::test_a_comment_is_not_a_difference",),
        full_copy=True,
    ),
    Mutant(
        "M537_THE_ROOT_EXCUSE_SWALLOWS_A_REAL_DIFFERENCE",
        "scripts/verify_installed_units.py",
        "        if text is not None and root is not None and installed_root not in (None, root):",
        "        if text is not None:",
        (
            "apps/api/tests/test_installed_units.py::"
            "test_the_same_root_still_shows_a_real_difference",
        ),
        full_copy=True,
    ),
    Mutant(
        "M544_THE_TRUNK_IS_JUDGED_BY_COMMIT_COUNT_AGAIN",
        "scripts/verify_canonical_state.py",
        "    if days > ceiling:",
        "    if False:",
        (
            "apps/api/tests/test_canonical_state.py::"
            "test_the_trunk_is_judged_by_age_not_by_commit_count",
        ),
        full_copy=True,
    ),
    Mutant(
        "M545_A_MISSING_DATE_IS_TREATED_AS_ZERO_AGE",
        "scripts/verify_canonical_state.py",
        "    if not earlier or not later:",
        "    if False:",
        (
            "apps/api/tests/test_canonical_state.py::"
            "test_age_is_measured_between_two_dates_and_missing_one_is_unknown",
        ),
        full_copy=True,
    ),
    Mutant(
        "M574_A_MOVABLE_TAG_COUNTS_AS_A_PINNED_ACTION",
        "scripts/gcp/production_contract.py",
        '_FULL_SHA_PIN = re.compile(r"@[0-9a-f]{40}$")',
        '_FULL_SHA_PIN = re.compile(r"@")',
        (
            "apps/api/tests/test_gcp_production_contract.py::"
            "test_action_pins_assert_the_property_not_a_fixed_list_of_shas",
        ),
        full_copy=True,
    ),
    Mutant(
        "M575_A_WORKFLOW_WITH_NO_ACTIONS_PASSES_THE_PIN_CONTRACT",
        "scripts/gcp/production_contract.py",
        "        bool(third_party) and all(_FULL_SHA_PIN.search(ref) for ref in third_party),",
        "        all(_FULL_SHA_PIN.search(ref) for ref in third_party),",
        (
            "apps/api/tests/test_gcp_production_contract.py::"
            "test_action_pins_assert_the_property_not_a_fixed_list_of_shas",
        ),
        full_copy=True,
    ),
    Mutant(
        "M576_A_WILDCARD_ORIGIN_PASSES_AS_AN_ADDRESS",
        "scripts/check_public_env_parity.py",
        '_ORIGIN = re.compile(r"^https?://[A-Za-z0-9._-]+(?::\\d+)?$")',
        '_ORIGIN = re.compile(r".")',
        (
            "apps/api/tests/test_public_env_parity.py::"
            "test_a_wildcard_origin_is_refused_because_it_is_not_an_address",
        ),
        full_copy=True,
    ),
    Mutant(
        "M577_AN_EMPTY_ORIGIN_LIST_IS_A_QUIET_SUCCESS",
        "scripts/check_public_env_parity.py",
        "    if not origins:",
        "    if False:",
        (
            "apps/api/tests/test_public_env_parity.py::test_an_empty_origin_list_is_a_quiet_success"
            if False
            else "apps/api/tests/test_public_env_parity.py::"
            "test_an_empty_origin_list_is_a_refusal_not_a_quiet_success",
        ),
        full_copy=True,
    ),
    Mutant(
        "M578_THE_TWO_DECLARATIONS_MAY_DISAGREE_ON_THE_ALLOWED_ORIGIN",
        "scripts/check_public_env_parity.py",
        '    "KORPUS_CORS_ORIGINS": "https://korpus-web-3cd81d.gitlab.io",\n}',
        "}",
        (
            "apps/api/tests/test_public_env_parity.py::"
            "test_the_two_declarations_may_not_disagree_on_the_allowed_origin",
        ),
        full_copy=True,
    ),
    Mutant(
        "M570_A_BRANCH_WITH_ITS_OWN_COMMITS_NEED_NOT_BE_NAMED",
        "scripts/verify_branch_integration.py",
        "    unnamed = sorted(set(diverged) - set(named))",
        "    unnamed = []",
        (
            "apps/api/tests/test_branch_integration.py::"
            "test_a_branch_with_its_own_commits_must_be_named",
        ),
        full_copy=True,
    ),
    Mutant(
        "M571_A_RECORD_ABOUT_AN_ALREADY_MERGED_BRANCH_SURVIVES",
        "scripts/verify_branch_integration.py",
        "    merged = sorted(set(named) - set(diverged))",
        "    merged = []",
        (
            "apps/api/tests/test_branch_integration.py::"
            "test_a_record_about_an_already_merged_branch_is_refused",
        ),
        full_copy=True,
    ),
    Mutant(
        "M572_AN_ENTRY_MAY_STAY_SILENT_ABOUT_WHAT_IT_CARRIES",
        "scripts/verify_branch_integration.py",
        '        and not (isinstance(entry.get("carries"), str) and len(entry["carries"].strip()) >= 20)',
        "        and False",
        (
            "apps/api/tests/test_branch_integration.py::"
            "test_an_entry_that_does_not_say_what_it_carries_is_refused",
        ),
        full_copy=True,
    ),
    Mutant(
        "M573_A_CLEAN_BRANCH_MAY_LINGER_WITHOUT_A_REASON",
        "scripts/verify_branch_integration.py",
        '        if state.get("clean") and not named.get(branch, {}).get("clean_but_held")',
        "        if False",
        (
            "apps/api/tests/test_branch_integration.py::"
            "test_a_cleanly_merging_branch_may_not_linger_without_a_reason",
        ),
        full_copy=True,
    ),
    Mutant(
        "M538_A_DIVERGED_TRUNK_IS_REPORTED_AS_MERELY_BEHIND",
        "scripts/verify_canonical_state.py",
        "    elif not ancestor:",
        "    elif False:",
        (
            "apps/api/tests/test_canonical_state.py::"
            "test_a_trunk_that_diverged_is_not_merely_behind",
        ),
        full_copy=True,
    ),
    Mutant(
        "M539_AN_UNDECLARED_PUBLICATION_SURFACE_IS_ACCEPTED",
        "scripts/verify_canonical_state.py",
        "    extra = sorted(seen - known)",
        "    extra = []",
        (
            "apps/api/tests/test_canonical_state.py::"
            "test_an_undeclared_publication_surface_is_refused",
        ),
        full_copy=True,
    ),
    Mutant(
        "M540_THE_UNDECIDED_REMOTE_QUIETLY_COUNTS_AS_DECIDED",
        "scripts/verify_canonical_state.py",
        "    if live:",
        "    if False:",
        (
            "apps/api/tests/test_canonical_state.py::"
            "test_the_undecided_remote_is_named_and_stays_red_until_decided",
        ),
        full_copy=True,
    ),
    Mutant(
        "M541_A_REMOTE_URL_THAT_DIFFERS_FROM_THE_DECLARED_ONE_IS_ACCEPTED",
        "scripts/verify_canonical_state.py",
        '        if entry.get("url") and url != entry["url"]:',
        "        if False:",
        (
            "apps/api/tests/test_canonical_state.py::"
            "test_a_remote_pointing_somewhere_else_than_declared_is_refused",
        ),
        full_copy=True,
    ),
    Mutant(
        "M542_TRANSIENT_WORKTREES_COUNT_AGAINST_THE_CEILING",
        "scripts/verify_canonical_state.py",
        "        if not any(path.startswith(prefix) for prefix in transient)",
        "        if True",
        (
            "apps/api/tests/test_canonical_state.py::"
            "test_transient_session_worktrees_do_not_count_against_the_ceiling",
        ),
        full_copy=True,
    ),
    Mutant(
        "M543_A_NON_CANONICAL_ROOT_IS_JUDGED_AS_IF_IT_WERE_CANONICAL",
        "scripts/verify_canonical_state.py",
        '    if observation.get("root") != declared_root:',
        "    if False:",
        (
            "apps/api/tests/test_canonical_state.py::"
            "test_a_worktree_that_is_not_the_canonical_root_cannot_judge_the_checkout",
        ),
        full_copy=True,
    ),
    Mutant(
        "M519_A_DECLARED_SELFTEST_THAT_NEVER_RAN_COUNTS_AS_GREEN",
        "scripts/verify_selftest_coverage.py",
        "    missed = sorted(set(expected) - seen)",
        "    missed = []",
        (
            "apps/api/tests/test_selftest_coverage.py::"
            "test_a_declared_selftest_that_did_not_run_is_not_a_silent_pass",
        ),
        full_copy=True,
    ),
    Mutant(
        "M520_A_MENTION_OF_THE_FLAG_COUNTS_AS_DECLARING_IT",
        "scripts/verify_selftest_coverage.py",
        r'''DECLARES = re.compile(r"""add_argument\(\s*["']--selftest["']""")''',
        'DECLARES = re.compile(r"--selftest")',
        (
            "apps/api/tests/test_selftest_coverage.py::"
            "test_discovery_finds_the_declarations_not_the_mentions",
        ),
        full_copy=True,
    ),
    Mutant(
        "M530_A_FAILING_SELFTEST_DOES_NOT_REDDEN_THE_GATE",
        "scripts/verify_selftest_coverage.py",
        '    failed = sorted(item["script"] for item in results if item["verdict"] != "PASS")',
        "    failed = []",
        ("apps/api/tests/test_selftest_coverage.py::test_a_failing_selftest_reddens",),
        full_copy=True,
    ),
    Mutant(
        "M531_A_STORE_DECLARED_EMPTY_IS_TAKEN_ON_TRUST",
        "scripts/verify_evidence_stores.py",
        '        and observation["stores"][path].get("documents") not in (0, None)',
        "        and False",
        (
            "apps/api/tests/test_evidence_stores.py::"
            "test_a_store_declared_empty_is_measured_not_trusted",
        ),
        full_copy=True,
    ),
    Mutant(
        "M500_A_MISSING_FILE_SILENTLY_BECOMES_A_DIFFERENT_DATABASE",
        "scripts/validate_span_hygiene.py",
        '    if "/" in database or database.endswith((".db", ".sqlite", ".sqlite3")):',
        "    if False:",
        (
            "apps/api/tests/test_span_hygiene_backend.py::"
            "test_a_path_that_does_not_exist_is_still_sqlite",
        ),
        full_copy=True,
    ),
    Mutant(
        "M501_THE_SQLITE_SCHEME_IS_HANDED_TO_PSQL",
        "scripts/validate_span_hygiene.py",
        '    if database.startswith("sqlite:"):',
        "    if False:",
        (
            "apps/api/tests/test_span_hygiene_backend.py::"
            "test_the_sqlite_scheme_keeps_the_absolute_path",
        ),
        full_copy=True,
    ),
    Mutant(
        "M502_A_NAMED_FILE_THAT_IS_ABSENT_IS_ASKED_OF_ANOTHER_DATABASE",
        "scripts/validate_span_hygiene.py",
        "        if not Path(target).is_file():",
        "        if False:",
        (
            "apps/api/tests/test_span_hygiene_backend.py::"
            "test_a_named_file_that_is_missing_is_a_refusal_not_another_database",
        ),
        full_copy=True,
    ),
    Mutant(
        "M503_A_TARGET_WITH_TWO_RECIPES_IS_NOT_REPORTED",
        "scripts/verify_gate_closure.py",
        "    duplicates = duplicate_recipes(makefile)",
        "    duplicates = []",
        (
            "apps/api/tests/test_gate_closure.py::"
            "test_a_duplicated_target_reddens_on_the_real_makefile",
        ),
        full_copy=True,
    ),
    Mutant(
        "M504_A_SECOND_HEADER_WITHOUT_A_RECIPE_IS_CALLED_A_DUPLICATE",
        "scripts/verify_gate_closure.py",
        "            if current is not None and current not in counted and line.strip():",
        "            if current is not None:",
        ("apps/api/tests/test_gate_closure.py::test_a_second_header_without_a_recipe_is_legal",),
        full_copy=True,
    ),
    Mutant(
        "M505_THE_REASON_REQUIRES_ARGUMENT_IS_TAKEN_ON_TRUST",
        "scripts/verify_gate_closure.py",
        "        and not mandatory_variables(all_recipes.get(target, []))",
        "        and False",
        (
            "apps/api/tests/test_gate_closure.py::"
            "test_the_reason_requires_argument_is_itself_checked",
        ),
        full_copy=True,
    ),
    Mutant(
        "M506_A_VARIABLE_ONLY_INSIDE_AN_IF_COUNTS_AS_MANDATORY",
        "scripts/verify_gate_closure.py",
        '    for opener in ("$(if ", "$(or "):',
        "    for opener in ():",
        (
            "apps/api/tests/test_gate_closure.py::"
            "test_a_variable_only_inside_an_if_is_not_a_requirement",
        ),
        full_copy=True,
    ),
    Mutant(
        "M464_A_REPORT_ABOUT_A_MOVED_CORPUS_STILL_CREDITS_ITS_AXIS",
        "scripts/check_answer_axes.py",
        '    if identity_digest(corpus_identity(database)) != recorded.get("corpus"):',
        "    if False:",
        (
            "apps/api/tests/test_report_input_binding.py::"
            "test_a_changed_corpus_is_named_as_the_thing_that_moved",
        ),
        full_copy=True,
    ),
    Mutant(
        "M465_A_REPORT_MADE_BY_A_DIFFERENT_MEASURER_STILL_COUNTS",
        "scripts/check_answer_axes.py",
        '    if hashlib.sha256(script.read_bytes()).hexdigest() != recorded.get("measurer"):',
        "    if False:",
        (
            "apps/api/tests/test_report_input_binding.py::"
            "test_a_changed_measurer_is_named_as_the_thing_that_moved",
        ),
        full_copy=True,
    ),
    Mutant(
        "M466_THE_IDENTITY_IGNORES_THE_LINKS_IT_IS_SUPPOSED_TO_COVER",
        "scripts/corpus_identity.py",
        "            \"select coalesce(source_uri, '') from document_versions order by id\"",
        "            \"select '' from document_versions order by id\"",
        (
            "apps/api/tests/test_report_input_binding.py::"
            "test_the_identity_moves_when_a_link_changes",
        ),
        full_copy=True,
    ),
    Mutant(
        "M467_THE_IDENTITY_IS_TAKEN_FROM_THE_FILE_NOT_THE_CONTENT",
        "scripts/corpus_identity.py",
        '            digest.update(str(text_hash).encode("ascii"))',
        "            pass",
        (
            "apps/api/tests/test_report_input_binding.py::"
            "test_the_identity_moves_when_a_quote_changes",
        ),
        full_copy=True,
    ),
    Mutant(
        "M483_A_QUESTION_THE_SYSTEM_MUST_REFUSE_COUNTS_AS_A_COVERAGE_GAP",
        "scripts/measure_declared_coverage.py",
        '            if str(case.get("kind", "")) in {"refusal", "adversarial"}:',
        "            if False:",
        (
            "apps/api/tests/test_declared_coverage.py::"
            "test_a_question_the_system_must_refuse_is_not_a_coverage_gap",
        ),
        full_copy=True,
    ),
    Mutant(
        "M484_A_QUESTION_SAMPLED_FROM_THE_CORPUS_IS_COUNTED_AS_A_DECLARATION",
        "scripts/measure_declared_coverage.py",
        '                        "sampled": bool(case.get("sampled_from_version")),',
        '                        "sampled": False,',
        (
            "apps/api/tests/test_declared_coverage.py::"
            "test_a_question_sampled_from_the_corpus_is_kept_apart",
        ),
        full_copy=True,
    ),
    Mutant(
        "M485_COVERAGE_IS_TAKEN_FROM_THE_COMMONEST_TERM_NOT_THE_RAREST",
        "scripts/measure_declared_coverage.py",
        "    return (min(count for _, count in counts) if counts else 0), counts",
        "    return (max(count for _, count in counts) if counts else 0), counts",
        (
            "apps/api/tests/test_declared_coverage.py::"
            "test_the_rarest_term_decides_because_one_gap_is_enough",
        ),
        full_copy=True,
    ),
    Mutant(
        "M486_FUNCTION_WORDS_COUNT_AS_EVIDENCE_OF_COVERAGE",
        "scripts/measure_declared_coverage.py",
        "    return [word for word in _WORD.findall(question.lower()) if word not in STOP]",
        "    return list(_WORD.findall(question.lower()))",
        (
            "apps/api/tests/test_declared_coverage.py::"
            "test_function_words_are_not_evidence_of_coverage",
        ),
        full_copy=True,
    ),
    Mutant(
        "M487_THE_SUBJECT_CLASS_IS_FLAT_AGAIN",
        "apps/api/src/korpus/application/retrieval.py",
        "        return float(subject_documents.get(key, 0))",
        "        return 1.0 if key in subject_documents else 0.0",
        (
            "apps/api/tests/test_authority_ranking.py::"
            "test_a_more_specific_declared_subject_outranks_one_that_is_merely_its_substring",
        ),
    ),
    Mutant(
        "M489_A_RECORDED_LEDGER_HEAD_IS_NEVER_COMPARED",
        "scripts/check_answer_axes.py",
        '    head = recorded.get("audit_head")',
        "    head = None",
        (
            "apps/api/tests/test_report_input_binding.py::"
            "test_a_recorded_input_the_gate_ignores_is_worse_than_none",
        ),
        full_copy=True,
    ),
    Mutant(
        "M490_THE_CORPUS_IDENTITY_MOVES_WITH_EVERY_ANSWER_AGAIN",
        "scripts/corpus_identity.py",
        '        "span_text_digest": digest.hexdigest(),',
        '        "span_text_digest": digest.hexdigest(),\n        "audit_head": connection.execute("select head_hash from audit_heads").fetchone()[0],',
        (
            "apps/api/tests/test_report_input_binding.py::"
            "test_housekeeping_does_not_move_the_identity",
        ),
        full_copy=True,
    ),
    # ── Приймальна перевірка зведення. Сторож, який довіряє власному застарілому
    # входові, видає непроміряний стан за перевірений — і саме це сталося 01.09.2026.
    Mutant(
        "M553_A_LANE_REPORT_OLDER_THAN_HEAD_IS_STILL_TRUSTED",
        "scripts/verify_branch_consolidation.py",
        "    return moment < head_epoch",
        "    return False",
        (
            "apps/api/tests/test_branch_consolidation.py::"
            "test_a_report_taken_before_the_head_is_stale",
        ),
        full_copy=True,
    ),
    Mutant(
        "M554_A_ROOT_OF_THE_CHAIN_IS_MISTAKEN_FOR_A_NAME",
        "scripts/verify_branch_consolidation.py",
        '            return None if value in {"None", ""} else value',
        "            return value",
        ("apps/api/tests/test_branch_consolidation.py::test_none_is_absence_not_a_name",),
        full_copy=True,
    ),
    Mutant(
        "M555_A_COMMENTED_ASSIGNMENT_INVENTS_A_REVISION",
        "scripts/verify_branch_consolidation.py",
        '        if stripped.startswith((f"{name} =", f"{name}:")):',
        '        if f"{name} =" in stripped:',
        (
            "apps/api/tests/test_branch_consolidation.py::"
            "test_a_commented_line_is_not_an_assignment",
        ),
        full_copy=True,
    ),
    # ── Сплячі підсистеми. Гейт мусить падати в ОБИДВА боки: той, що ловить лише
    # пробудження, не помітить тихого видалення, і реєстр стане описом неіснуючого.
    Mutant(
        "M549_A_PACKAGE_IMPORT_HIDES_THE_MODULE_IT_BRINGS",
        "scripts/check_dormant_subsystems.py",
        '    children = {f"{node.module}.{alias.name}" for alias in node.names}',
        "    children = set[str]()",
        (
            "apps/api/tests/test_dormant_subsystems.py::"
            "test_the_import_graph_keeps_the_edge_a_package_import_hides",
        ),
        full_copy=True,
    ),
    Mutant(
        "M550_A_SUBSYSTEM_THAT_WOKE_UP_IS_STILL_CALLED_DORMANT",
        "scripts/check_dormant_subsystems.py",
        "        woke = sorted(module for module in declared if module in reachable)",
        "        woke = []",
        (
            "apps/api/tests/test_dormant_subsystems.py::"
            "test_a_module_wired_into_the_api_wakes_the_subsystem",
        ),
        full_copy=True,
    ),
    Mutant(
        "M551_A_MODULE_THAT_VANISHED_IS_NOT_REPORTED",
        "scripts/check_dormant_subsystems.py",
        "        gone = sorted(module for module in declared if module not in every_module)",
        "        gone = []",
        ("apps/api/tests/test_dormant_subsystems.py::test_a_module_that_vanished_is_a_change",),
        full_copy=True,
    ),
    Mutant(
        "M552_AN_ABSENT_TABLE_IS_READ_AS_AN_EMPTY_ONE",
        "scripts/check_dormant_subsystems.py",
        "        absent = sorted(table for table, rows in counts.get(name, {}).items() if rows is None)",
        "        absent = []",
        (
            "apps/api/tests/test_dormant_subsystems.py::"
            "test_a_table_that_disappeared_is_a_change_too",
        ),
        full_copy=True,
    ),
    # ── Бігун лану. `make -k` дає два стани; тут первинний саме ТРЕТІЙ, і мутанти
    # цілять у нього: невиконане, зараховане як пройдене, — це і є та вада.
    Mutant(
        "M546_A_TARGET_NEVER_REACHED_IS_COUNTED_AS_PASSED",
        "scripts/run_lane.py",
        '        name: {"state": NOT_RUN, "code": None, "seconds": 0.0} for name in targets',
        '        name: {"state": PASSED, "code": 0, "seconds": 0.0} for name in targets',
        (
            "apps/api/tests/test_lane_report.py::"
            "test_a_target_the_runner_never_reached_stays_not_run_on_disk",
        ),
        full_copy=True,
    ),
    Mutant(
        "M547_A_LANE_WITH_UNMEASURED_TARGETS_STILL_CALLS_ITSELF_MEASURED",
        "scripts/run_lane.py",
        '        "status": "MEASURED" if counts[NOT_RUN] == 0 else "PARTIAL",',
        '        "status": "MEASURED",',
        ("apps/api/tests/test_lane_report.py::test_an_unreached_target_makes_the_lane_partial",),
        full_copy=True,
    ),
    Mutant(
        "M548_A_TIMED_OUT_TARGET_IS_A_PASS",
        "scripts/run_lane.py",
        '        return {"state": TIMED_OUT, "code": None, "seconds": round(time.monotonic() - started, 1)}',
        '        return {"state": PASSED, "code": 0, "seconds": round(time.monotonic() - started, 1)}',
        (
            "apps/api/tests/test_lane_report.py::"
            "test_a_timeout_is_recorded_as_a_timeout_by_the_runner_itself",
        ),
        full_copy=True,
    ),
    # ── Допуск оголошеного предмета за початком слова. Дослівний підрядок вимагав від
    # людини називного відмінка: виміряно 1 із 14 у родовому проти 13 після зміни.
    Mutant(
        "M527_THE_SUBJECT_MUST_BE_SPELLED_AS_THE_TITLE_SPELLS_IT",
        "apps/api/src/korpus/application/declared_subject.py",
        "            any(asked[:MIN_PREFIX] == word[:MIN_PREFIX] for asked in question_words)",
        "            any(asked == word for asked in question_words)",
        (
            "apps/api/tests/test_declared_subject_token_space.py::"
            "test_the_subject_is_found_in_the_genitive",
        ),
    ),
    Mutant(
        "M528_ANY_ONE_WORD_OF_THE_SUBJECT_IS_ENOUGH_TO_ADMIT_IT",
        "apps/api/src/korpus/application/declared_subject.py",
        "        if all(",
        "        if any(",
        (
            "apps/api/tests/test_declared_subject_token_space.py::"
            "test_a_neighbouring_role_is_not_admitted",
        ),
    ),
    Mutant(
        "M529_A_SUBJECT_OF_ONLY_SHORT_WORDS_IS_ADMITTED_AGAIN",
        "apps/api/src/korpus/application/declared_subject.py",
        "        if not significant:\n            continue",
        "        if False:\n            continue",
        (
            "apps/api/tests/test_declared_subject_token_space.py::"
            "test_a_subject_with_no_long_word_is_not_admitted",
        ),
    ),
    # ── Друга форма питання. Лінійка, що зараховує довшу роль за коротшу або цитату
    # не першою, показала б високе число там, де воно 1/14.
    Mutant(
        "M525_A_LONGER_ROLE_COUNTS_AS_THE_ROLE_ASKED_FOR",
        "scripts/benchmark_subject_precision.py",
        "    return declared_subject(cited[0]) == role",
        '    return cited[0].replace("\u2019", "\'").startswith(f"Обов\'язки: {role} ")',
        (
            "apps/api/tests/test_subject_inflection.py::"
            "test_a_longer_role_that_starts_the_same_is_not_the_role",
        ),
        full_copy=True,
    ),
    Mutant(
        "M526_THE_ROLE_CITED_ANYWHERE_COUNTS_AS_CITED_FIRST",
        "scripts/benchmark_subject_precision.py",
        "    return declared_subject(cited[0]) == role",
        "    return any(declared_subject(title) == role for title in cited)",
        (
            "apps/api/tests/test_subject_inflection.py::"
            "test_the_same_document_cited_second_does_not",
        ),
        full_copy=True,
    ),
    # ── Свіжість обслуговуючого процесу. П'ять осей міряються запитом до сервера, тож
    # вони кредитують ПРОЦЕС, а не дерево, і жодне поле звіту про це не каже.
    Mutant(
        "M523_A_SERVER_OLDER_THAN_THE_CODE_STILL_COUNTS_AS_SERVING_IT",
        "scripts/check_serving_freshness.py",
        '    judged = [{**item, "serves_current_code": item["started_epoch"] >= stamp} for item in processes]',
        '    judged = [{**item, "serves_current_code": True} for item in processes]',
        (
            "apps/api/tests/test_serving_freshness.py::"
            "test_a_process_older_than_the_code_does_not_serve_the_tree",
        ),
        full_copy=True,
    ),
    Mutant(
        "M524_NO_SERVING_PROCESS_COUNTS_AS_AGREEMENT",
        "scripts/check_serving_freshness.py",
        '        "status": "MEASURED" if judged else "UNKNOWN",',
        '        "status": "MEASURED",',
        (
            "apps/api/tests/test_serving_freshness.py::"
            "test_no_serving_process_is_unknown_rather_than_agreement",
        ),
        full_copy=True,
    ),
    Mutant(
        "M522_THE_DIRECTIVE_SET_WIDENS_UNTIL_EVERYTHING_IS_ACTIONABLE",
        "scripts/measure_declared_coverage.py",
        '    r"проводиться|виконується|застосовується|вживає|вживають)",',
        '    r"проводиться|виконується|застосовується|вживає|вживають|вивча|перелік|опис)",',
        (
            "apps/api/tests/test_declared_coverage.py::"
            "test_the_directive_set_is_narrow_enough_to_separate",
        ),
        full_copy=True,
    ),
    # ── Бази доказів. Гейт проти неоголошених баз, який сам спирається на оголошення,
    # зелений саме в тому стані, заради якого існує: M498 — це та отрута, що проходила.
    Mutant(
        "M498_A_BASE_EXISTS_ONLY_IF_THE_REGISTRY_NAMES_IT",
        "scripts/measure_evidence_bases.py",
        "                found.setdefault(fingerprint(value), entry.name)",
        "                pass",
        (
            "apps/api/tests/test_evidence_bases.py::"
            "test_discovery_reads_the_environment_of_live_processes",
        ),
        full_copy=True,
    ),
    Mutant(
        "M499_A_DECLARATION_THAT_STOPPED_BEING_TRUE_IS_TOLERATED",
        "scripts/measure_evidence_bases.py",
        "        if key in declared and declared[key] != actual[key]",
        "        if False",
        (
            "apps/api/tests/test_evidence_bases.py::"
            "test_a_declaration_that_says_the_same_about_a_base_that_differs_fails",
        ),
        full_copy=True,
    ),
    Mutant(
        "M521_THE_PUBLISHED_FINGERPRINT_CARRIES_THE_PASSWORD",
        "scripts/measure_evidence_bases.py",
        '        return f"postgres:{user}@{location}"',
        '        return f"postgres:{credentials}@{location}"',
        (
            "apps/api/tests/test_evidence_bases.py::test_the_fingerprint_does_not_carry_the_password",
        ),
        full_copy=True,
    ),
    # ── Навчальний шар: 1516 рядків коду й 1036 рядків тестів, і ЖОДНОГО мутанта до
    # 01.09.2026. Жоден маршрут API його не імпортує, усі його таблиці порожні в обох
    # базах — тобто «тести є» було твердженням, яке ніхто не перевіряв. Шість мутантів
    # цілять у шість РІЗНИХ тверджень цього шару, а не в шість рядків одного.
    Mutant(
        "M492_A_SUPERSET_OF_THE_CORRECT_ANSWERS_COUNTS_AS_CORRECT",
        "apps/api/src/korpus/application/learning_assessment.py",
        "    correct = attempt.selected_option_ids == check.correct_option_ids",
        "    correct = attempt.selected_option_ids >= check.correct_option_ids",
        (
            "apps/api/tests/test_learning_assessment.py::"
            "test_extra_selection_does_not_receive_partial_credit",
        ),
    ),
    Mutant(
        "M493_AN_ATTEMPT_MAY_NAME_AN_OPTION_THAT_DOES_NOT_EXIST",
        "apps/api/src/korpus/application/learning_assessment.py",
        "    unknown = attempt.selected_option_ids.difference(declared)",
        "    unknown = frozenset[str]()",
        ("apps/api/tests/test_learning_assessment.py::test_attempt_rejects_undeclared_options",),
    ),
    Mutant(
        "M494_A_CHECK_MAY_TEACH_AN_OBJECTIVE_THE_LESSON_DOES_NOT_HAVE",
        "apps/api/src/korpus/application/learning_assessment.py",
        "    if check.objective_id not in objective_ids:",
        "    if objective_ids and check.objective_id not in sorted(objective_ids)[:0]:",
        ("apps/api/tests/test_learning_assessment.py::test_a_well_bound_check_has_no_blockers",),
    ),
    Mutant(
        "M495_ANY_OVERLAP_OF_EVIDENCE_SPANS_IS_ENOUGH_TO_PUBLISH",
        "apps/api/src/korpus/domain/learning.py",
        "            if not binding.evidence_span_ids <= state.evidence_span_ids:",
        "            if not binding.evidence_span_ids & state.evidence_span_ids:",
        (
            "apps/api/tests/test_learning_course_domain.py::"
            "test_a_binding_that_cites_one_held_span_and_one_absent_span_is_rejected",
        ),
    ),
    Mutant(
        "M496_ONLY_RESCISSION_STOPS_PUBLICATION_NOT_APPROVAL_OR_WINDOW",
        "apps/api/src/korpus/domain/learning.py",
        "            if not state.is_effective(observed):",
        "            if state.rescinded_at is not None:",
        (
            "apps/api/tests/test_learning_course_domain.py::"
            "test_publication_validation_rejects_unapproved_source",
        ),
    ),
    Mutant(
        "M497_A_PREREQUISITE_CYCLE_IS_SEEN_AND_NOT_REPORTED",
        "apps/api/src/korpus/domain/learning.py",
        '            violations.add(f"{CourseGraphViolation.PREREQUISITE_CYCLE}:{lesson_id}")',
        "            pass",
        (
            "apps/api/tests/test_learning_course_domain.py::"
            "test_publication_validation_detects_prerequisite_cycle_deterministically",
        ),
    ),
    Mutant(
        "M491_THE_SUBJECT_IS_PARSED_IN_A_DIFFERENT_SPACE_FROM_THE_QUESTION",
        "apps/api/src/korpus/application/declared_subject.py",
        "            tokens.update(tokenize(subject))",
        r'            tokens.update(re.findall(r"\w+", subject.lower()))',
        (
            "apps/api/tests/test_declared_subject_token_space.py::"
            "test_subject_tokens_are_produced_by_the_same_parser_as_the_question",
        ),
    ),
    Mutant(
        "M488_THE_MATCH_LENGTH_IS_DISCARDED_BEFORE_RANKING",
        "apps/api/src/korpus/application/declared_subject.py",
        "                specificity[document_id] = max(specificity.get(document_id, 0), len(subject))",
        "                specificity[document_id] = 1",
        (
            "apps/api/tests/test_declared_subject_specificity.py::"
            "test_the_ranker_receives_the_length_of_the_match",
        ),
    ),
    Mutant(
        "M441_AUTHORITY_OUTRANKS_A_SOURCE_IT_DOES_NOT_ANSWER_WITH",
        "apps/api/src/korpus/application/retrieval.py",
        "    return priors[item.version.authority] if item.score >= tier_floor else 0.0",
        "    return priors[item.version.authority]",
        (
            "apps/api/tests/test_authority_ranking.py::"
            "test_a_class_does_not_outrank_a_source_it_is_not_comparably_responsive_to",
        ),
    ),
    Mutant(
        "M442_THE_FLOOR_QUIETLY_BECOMES_PURE_SIMILARITY_RANKING",
        "apps/api/src/korpus/application/retrieval.py",
        "    return relevance_floor * max((item.score for item in ranked), default=0.0)",
        "    return 2.0",
        (
            "apps/api/tests/test_authority_ranking.py::"
            "test_a_comparably_responsive_official_source_still_outranks_a_better_match",
        ),
    ),
    # ── Паритет двох оголошень оточення. Отрути по ПРАВИЛУ, не по переліку змінних.
    Mutant(
        "M450_A_VARIABLE_MISSING_FROM_THE_UNIT_IS_TOLERATED",
        "scripts/check_public_env_parity.py",
        "    missing_in_unit = sorted(normalised_shell - unit_names)",
        "    missing_in_unit: list[str] = []",
        (
            "apps/api/tests/test_public_env_parity.py::test_a_variable_the_script_declares_and_the_unit_lacks_is_refused",
        ),
        full_copy=True,
    ),
    Mutant(
        "M451_A_DRIFTED_SAFETY_VALUE_IS_TOLERATED",
        "scripts/check_public_env_parity.py",
        "        if unit.get(name) != expected or shell.get(name) != expected",
        "        if False",
        ("apps/api/tests/test_public_env_parity.py::test_a_safety_value_that_drifts_is_refused",),
        full_copy=True,
    ),
    Mutant(
        "M452_A_SECRET_BY_VALUE_IN_THE_UNIT_IS_TOLERATED",
        "scripts/check_public_env_parity.py",
        '    leaked = sorted(name for name in unit if name.endswith("_SECRET"))',
        "    leaked: list[str] = []",
        (
            "apps/api/tests/test_public_env_parity.py::test_a_secret_by_value_in_the_unit_is_refused",
        ),
        full_copy=True,
    ),
    # ── Ратчет прийнятого боргу розгортання.
    Mutant(
        "M460_WORSENING_PAST_THE_CEILING_IS_TOLERATED",
        "scripts/check_deployment_debt.py",
        "    if measured > ceiling:",
        "    if False:",
        ("apps/api/tests/test_deployment_debt.py::test_worsening_by_one_is_refused",),
        full_copy=True,
    ),
    Mutant(
        "M461_IMPROVEMENT_DOES_NOT_DEMAND_A_LOWER_CEILING",
        "scripts/check_deployment_debt.py",
        '            "lower_ceiling_to": measured,',
        '            "lower_ceiling_to": ceiling,',
        ("apps/api/tests/test_deployment_debt.py::test_improvement_demands_a_lower_ceiling",),
        full_copy=True,
    ),
    Mutant(
        "M462_A_BOOLEAN_COUNTS_AS_A_MEASUREMENT",
        "scripts/check_deployment_debt.py",
        "    return node if isinstance(node, int) and not isinstance(node, bool) else None",
        "    return node if isinstance(node, int) else None",
        ("apps/api/tests/test_deployment_debt.py::test_a_boolean_is_not_a_measurement",),
        full_copy=True,
    ),
    Mutant(
        "M463_AN_ENTRY_WITHOUT_A_CEILING_IS_ALLOWED",
        "scripts/check_deployment_debt.py",
        '        return {"target": target, "verdict": "FAIL", "detail": "стеля не є цілим числом"}',
        '        return {"target": target, "verdict": "PASS", "detail": "стеля не є цілим числом"}',
        (
            "apps/api/tests/test_deployment_debt.py::test_an_entry_without_a_ceiling_is_refused_not_allowed",
        ),
        full_copy=True,
    ),
    Mutant(
        "M470_AN_UNUSABLE_VALUE_IS_TOLERATED",
        "scripts/check_public_env_parity.py",
        '        name for name, value in unit.items() if value.startswith("{") and not _parses_as_json(value)',
        "        name for name, value in unit.items() if False and not _parses_as_json(value)",
        ("apps/api/tests/test_public_env_parity.py::test_an_unparsable_json_value_is_refused",),
        full_copy=True,
    ),
    Mutant(
        "M471_A_QUOTED_VALUE_IS_TRUNCATED_AT_THE_FIRST_QUOTE",
        "scripts/check_public_env_parity.py",
        '            found[match.group("qname")] = match.group("qvalue").replace(\'\\\\"\', \'"\').strip()',
        '            found[match.group("qname")] = match.group("qvalue").split("\\\\")[0].strip()',
        (
            "apps/api/tests/test_public_env_parity.py::test_a_quoted_value_with_escaped_quotes_survives_parsing",
        ),
        full_copy=True,
    ),
    # ── Проба некаталогізованих мутацій не сміє лишати стану в дереві.
    Mutant(
        "M480_THE_PROBE_EDITS_THE_SERVED_TREE_BY_DEFAULT",
        "scripts/probe_uncatalogued_mutation.py",
        "        if not args.in_place:",
        "        if False:",
        ("apps/api/tests/test_mutation_probe_safety.py::test_the_probe_edits_a_copy_by_default",),
        full_copy=True,
    ),
    Mutant(
        "M481_A_SIGNAL_BYPASSES_THE_RESTORE_AGAIN",
        "scripts/probe_uncatalogued_mutation.py",
        "    for received in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):",
        "    for received in ():",
        (
            "apps/api/tests/test_mutation_probe_safety.py::test_a_signal_does_not_bypass_the_restore",
        ),
        full_copy=True,
    ),
    Mutant(
        "M482_A_DEAD_HOLDER_STILL_HOLDS_THE_LOCK",
        "scripts/probe_uncatalogued_mutation.py",
        "    except (OSError, ProcessLookupError):\n        return False",
        "    except (OSError, ProcessLookupError):\n        return True",
        (
            "apps/api/tests/test_mutation_probe_safety.py::test_an_orphaned_lock_is_reported_as_an_event",
        ),
        full_copy=True,
    ),
    Mutant(
        # Дешевий добір і остаточна проєкція — ДВА написання одного правила, і саме
        # так вони розійшлися: `_visibility_filters` вимагає, щоб наступник належав
        # ТОМУ САМОМУ документові, а CTE добору цього не питав. Чужий документ,
        # оголосивши заміщення, викидав чужий проліт із кандидатів; остаточний фільтр
        # його вже не бачив і повертав «недостатньо підстав» про корпус, що має
        # відповідь. Дірки в доступі не було — була відмова у праві на відповідь.
        "M579_CANDIDATE_SUPERSESSION_CROSSES_DOCUMENTS",
        "apps/api/src/korpus/infrastructure/retrieval_candidate_query.py",
        "              AND (v.id, v.document_id) NOT IN"
        " (SELECT id, document_id FROM superseded)\n"
        "            ORDER BY bm25(evidence_fts), s.id",
        "              AND v.id NOT IN (SELECT id FROM superseded)\n"
        "            ORDER BY bm25(evidence_fts), s.id",
        (
            "apps/api/tests/test_candidate_visibility_equivalence.py::"
            "test_cross_document_supersession_cannot_remove_a_candidate",
        ),
    ),
    Mutant(
        # Відсіки в доборі не боронили доступу — його боронить остаточна проєкція.
        # Вони боронили БЮДЖЕТ: `LIMIT` спільний, і невидимі рядки витісняли з
        # верхівки видимі. Порядок видачі при цьому повідомляв про існування того,
        # чого читач бачити не може.
        "M580_CANDIDATE_BUDGET_SPENT_ON_INVISIBLE_COMPARTMENTS",
        "apps/api/src/korpus/infrastructure/retrieval_candidate_query.py",
        "    clause = (\n"
        '        "AND d.id NOT IN (SELECT dc.document_id FROM document_compartments dc "\n'
        '        f"WHERE 1=1 {forbidden})"\n'
        "    )",
        '    clause = ""\n    _unused_forbidden = forbidden',
        (
            "apps/api/tests/test_candidate_visibility_equivalence.py::"
            "test_invisible_compartment_rows_cannot_consume_candidate_budget",
        ),
    ),
    Mutant(
        # Дуал до M580, і тихіший за нього. M580 питає, що ПРОХОДИТЬ не маючи права;
        # цей — що ВІДХИЛЯЄТЬСЯ, маючи його. Без `forbidden` читач із призначеним
        # відсіком не бачить у доборі жодного відсіченого документа, тобто гейт стає
        # суворішим за правило, яке він виражає, і мовчки звужує корпус.
        "M581_AN_ASSIGNED_COMPARTMENT_IS_REFUSED_TOO",
        "apps/api/src/korpus/infrastructure/retrieval_candidate_query.py",
        '        forbidden = f"AND dc.compartment NOT IN ({placeholders})"',
        '        forbidden = "" if placeholders else ""',
        (
            "apps/api/tests/test_candidate_visibility_equivalence.py::"
            "test_assigned_compartment_is_admitted_but_partial_assignment_is_not",
        ),
    ),
    Mutant(
        # Дірка, вмикна одним рядком конфігурації, — це не полагоджена дірка.
        "M582_POSTGRES_MAY_RUN_WITHOUT_THE_RLS_BOUNDARY",
        "apps/api/src/korpus/infrastructure/runtime.py",
        "    factory = (\n"
        "        RlsBoundSqlRepository"
        ' if settings.database_url.startswith("postgresql") else SqlRepository\n'
        "    )",
        "    factory = SqlRepository",
        (
            "apps/api/tests/test_rls_identity_boundary_wiring.py::"
            "test_postgres_always_gets_the_boundary_bound_repository",
        ),
    ),
    Mutant(
        # Брокер, що збігається із застосунковим логіном, — та сама дірка під іншим
        # ім'ям: підробити claim зміг би той самий, від кого межа боронить.
        "M583_THE_BROKER_MAY_BE_THE_APPLICATION_LOGIN",
        "apps/api/src/korpus/infrastructure/rls_repository.py",
        "        if not authz.username or authz.username == primary.username:\n"
        '            raise ValueError("authz database identity must use a distinct PostgreSQL login")',
        "        if not authz.username:\n"
        '            raise ValueError("authz database identity must use a distinct PostgreSQL login")',
        (
            "apps/api/tests/test_rls_identity_boundary_wiring.py::"
            "test_a_broker_that_is_not_a_separate_login_is_refused",
        ),
    ),
    Mutant(
        # Прив'язка особистості в доборі векторів: статичний виклик ставив `set_config`,
        # якого політики не читають, і вибірка ставала порожньою МОВЧКИ.
        "M584_EMBEDDING_BACKFILL_BINDS_IDENTITY_THE_OLD_WAY",
        "apps/api/src/korpus/infrastructure/embedding_backfill.py",
        "        self.bind_identity = bind_identity",
        "        self.bind_identity = None",
        (
            "apps/api/tests/test_embedding_backfill.py::"
            "test_the_batch_binds_the_identity_it_was_given",
        ),
    ),
    Mutant(
        # Дефолт замість відмови: реєстр, що перестав називати канон, читався б як
        # реєстр, який назвав правильно — і саме в момент переїзду канону.
        "M585_A_MISSING_CANONICAL_DECLARATION_GUESSES_MAIN",
        "scripts/canonical_declaration.py",
        '        raise CanonicalDeclarationMissing(f"{path} не називає канонічної гілки") '
        "from error",
        '        return "main"',
        (
            "apps/api/tests/test_canonical_declaration.py::"
            "test_a_registry_that_names_nothing_refuses_instead_of_guessing",
        ),
    ),
    Mutant(
        # Стовбур, оголошений тією самою гілкою, що й канон: перевірки відставання
        # стають тотожно істинними, і гейт зелений рівно в тому стані, заради якого існує.
        "M586_TRUNK_MAY_BE_THE_CANONICAL_BRANCH_ITSELF",
        "scripts/verify_canonical_state.py",
        '    if name == registry.get("canonical_branch"):',
        "    if False:",
        (
            "apps/api/tests/test_canonical_state.py::"
            "test_a_trunk_declared_as_the_canonical_branch_is_refused",
        ),
    ),
    Mutant(
        # Закритий борг без причини закриває його лише на вигляд.
        "M587_A_CLOSED_DEBT_NEED_NOT_SAY_WHY",
        "scripts/verify_canonical_state.py",
        '        isinstance(item, dict) and item.get("name") == name '
        'and str(item.get("why", "")).strip()',
        '        isinstance(item, dict) and item.get("name") == name',
        (
            "apps/api/tests/test_canonical_state.py::"
            "test_a_vanished_trunk_block_is_refused_unless_the_debt_was_closed",
        ),
    ),
    Mutant(
        # Без запасу агент бачить `answered` і не бачить, що відповідь пройшла
        # РІВНО по межі. Виміряно на живому: «Яка столиця Бразилії?» — запас 0.0.
        "M588_THE_AGENT_IS_NOT_TOLD_HOW_CLOSE_TO_THE_FLOOR_IT_IS",
        "apps/api/src/korpus/mcp/server.py",
        '                "at_floor": abs(float(value) - float(floor)) < 1e-9,',
        '                "at_floor": False,',
        ("apps/api/tests/test_mcp_server.py::test_an_answer_at_the_threshold_is_marked_as_such",),
    ),
    Mutant(
        # Власна константа замість опублікованого порога — це друга тотожність
        # «своє питання», яка розійдеться з першою мовчки.
        "M589_THE_TOOL_GUESSES_A_THRESHOLD_INSTEAD_OF_REFUSING",
        "apps/api/src/korpus/mcp/server.py",
        '            raise ToolFailure("korpus api does not publish its admission thresholds")',
        '            return {"min_query_coverage": 0.5, "min_retrieval_score": 0.18}',
        (
            "apps/api/tests/test_mcp_server.py::"
            "test_without_published_thresholds_the_tool_refuses_instead_of_guessing",
        ),
    ),
    Mutant(
        # Транспортна відмова, віддана як результат, — найтихіша підміна: агент
        # запише у висновок відсутність підстав, якої ніхто не міряв.
        "M590_A_TRANSPORT_FAILURE_LOOKS_LIKE_AN_ANSWER",
        "apps/api/src/korpus/mcp/stdio.py",
        '    body = {"error": reason, "retryable": retryable}',
        '    body = {"error": reason, "retryable": False}',
        (
            "apps/api/tests/test_mcp_server.py::"
            "test_a_transport_failure_is_not_reported_as_absent_grounds",
        ),
    ),
    Mutant(
        # Токен, який не може бути JWT, клав ВЕСЬ сервер `UnicodeEncodeError`ом
        # при складанні заголовка — агент лишався без причини й без з'єднання.
        "M591_A_TOKEN_THAT_CANNOT_BE_A_JWT_IS_ACCEPTED",
        "apps/api/src/korpus/mcp/transport.py",
        '            raise ValueError("korpus api token must be ASCII: a JWT cannot contain '
        'other bytes")',
        "            pass",
        (
            "apps/api/tests/test_mcp_server.py::"
            "test_a_token_that_cannot_be_a_jwt_is_refused_before_any_call",
        ),
    ),
    Mutant(
        # Термін дії, що не доходить до видавця, лишає кожен токен на годині —
        # і сесія агента вмирає посеред роботи 401'м, схожим на мовчання корпусу.
        "M592_THE_TOKEN_LIFETIME_NEVER_REACHES_THE_ISSUER",
        "apps/api/src/korpus/cli.py",
        "                print(issue_token(identity, settings, args.lifetime_minutes))",
        "                print(issue_token(identity, settings, 60))",
        (
            "apps/api/tests/test_boundary_coverage_v5.py::"
            "test_cli_read_commands_close_all_resources",
        ),
    ),
    Mutant(
        # Правило словника не бачить ЗНЯТОГО заперечення за побудовою: вилучення
        # слова не порушує вкладення множин. Для статуту це різниця між «не
        # ближче» і «ближче».
        "M593_A_DROPPED_NEGATION_INVERTS_THE_NORM_UNNOTICED",
        "apps/api/src/korpus/application/composition.py",
        "        if dropped and all(",
        "        if False and all(",
        (
            "apps/api/tests/test_answer_composition.py::"
            "test_a_dropped_negation_inverts_the_norm_and_the_vocabulary_rule_cannot_see_it",
        ),
    ),
    Mutant(
        # Дуал: «заперечене будь-де в цитаті» замість «безпосереднього сусідства»
        # робить непідтвердженим геть усе, що цитують із довгої цитати.
        "M594_ANY_NEGATION_IN_A_CITATION_REFUSES_EVERYTHING",
        "apps/api/src/korpus/application/composition.py",
        "        negated[token] = negated.get(token, True) and previous in _NEGATION",
        "        negated[token] = True",
        (
            "apps/api/tests/test_answer_composition.py::"
            "test_a_negation_elsewhere_in_a_long_citation_does_not_refuse_everything",
        ),
    ),
    Mutant(
        # Гуртовий вирок марний: агент мусить знати, ЯКЕ речення викинути.
        "M595_THE_DRAFT_IS_JUDGED_WHOLESALE",
        "apps/api/src/korpus/application/composition.py",
        '    for sentence in _SENTENCE.split(unicodedata.normalize("NFC", draft)):',
        '    for sentence in [unicodedata.normalize("NFC", draft)]:',
        (
            "apps/api/tests/test_answer_composition.py::"
            "test_the_verdict_is_per_sentence_not_wholesale",
        ),
    ),
    Mutant(
        # Один замок на всі середовища робить гейт нездійсненним: у продакшен-образі
        # dev-інструментів немає й бути не мусить, а на робочій машині інтерпретатор
        # не продакшенний. Стану, у якому гейт зелений, не існувало.
        "M596_ONE_LOCK_SET_FOR_EVERY_ENVIRONMENT",
        "scripts/run_exact_environment_gate.py",
        '    "runtime": (RUNTIME_LOCK,),',
        '    "runtime": (RUNTIME_LOCK, DEV_LOCK),',
        (
            "apps/api/tests/test_exact_environment_evidence.py::"
            "test_the_gate_has_a_state_in_which_it_can_be_green",
        ),
    ),
    Mutant(
        # Без вимоги профілю доказ робочої машини задовольняє продакшенний предикат
        # рівно тому, що хибної перевірки в ньому НЕМАЄ.
        "M597_A_DEVELOPMENT_REPORT_SATISFIES_THE_PRODUCTION_PREDICATE",
        "apps/api/src/korpus/application/production_hard_predicates.py",
        '        (("status", "PASS"), ("profile", "runtime")),',
        '        (("status", "PASS"),),',
        (
            "apps/api/tests/test_exact_environment_evidence.py::"
            "test_a_development_report_cannot_satisfy_the_production_predicate",
        ),
    ),
    Mutant(
        # Доказ знищується не хибним числом, а тим, що порожній результат займає
        # його місце. «Транспортна відмова не є вимірюванням» боронило ЧИСЛО;
        # файл воно не боронило.
        "M598_AN_EMPTY_RUN_OVERWRITES_A_MEASUREMENT",
        "scripts/benchmark_subject_precision.py",
        "    if total <= 0 or unreachable < total or not out.is_file():\n        return",
        "    if True:\n        return",
        (
            "apps/api/tests/test_subject_inflection.py::"
            "test_an_empty_run_may_not_overwrite_a_measured_report",
        ),
    ),
    Mutant(
        # Бік нерівності бісекції. Перевернутий, він шукає межу з іншого кінця й видає
        # число, яке виглядає правдоподібно і ЗАНИЖУЄ ризик — ловиться лише покриттям.
        "M599_THE_EXACT_BOUND_SEARCHES_FROM_THE_WRONG_SIDE",
        "apps/api/src/korpus/application/statistical_bounds.py",
        "        above = _binomial_tail_at_most(errors_i, samples_i, middle) > local_delta",
        "        above = _binomial_tail_at_most(errors_i, samples_i, middle) < local_delta",
        ("apps/api/tests/test_exact_risk_bound.py",),
    ),
    Mutant(
        # Замало кроків бісекції — межа недозбігається й недопокриває.
        #
        # Тут спершу стояла інша мутація: повертати `low` замість `high`. Вона ВИЖИЛА, і
        # це не діра в тестах, а еквівалентність, доведена рахунком: після 200 половинок
        # ширина інтервалу ~6e-61 при кроці double ~2e-16, тобто обидва кінці — той самий
        # float. Записано, бо «вижив» і «не перевіряється» тут різні речі, і наступний
        # прогін інакше витратив би вечір на пошук неіснуючої діри. Кінець бісекції не
        # навантажений; навантажена КІЛЬКІСТЬ кроків, і мутується саме вона.
        "M600_THE_EXACT_BOUND_STOPS_BISECTING_TOO_EARLY",
        "apps/api/src/korpus/application/statistical_bounds.py",
        "_BISECTION_STEPS = 200",
        "_BISECTION_STEPS = 8",
        ("apps/api/tests/test_exact_risk_bound.py::test_zero_errors_matches_the_closed_form",),
    ),
    Mutant(
        # Без поправки на кількість гіпотез межа обіцяє 1-delta там, де перевірок кілька.
        "M601_THE_EXACT_BOUND_DROPS_THE_UNION_CORRECTION",
        "apps/api/src/korpus/application/statistical_bounds.py",
        "    return _confidence_delta(delta) / hypotheses",
        "    return _confidence_delta(delta)",
        (
            "apps/api/tests/test_exact_risk_bound.py::test_the_bound_moves_in_the_only_two_"
            "directions_it_may",
        ),
    ),
    Mutant(
        # Ворота розгортання, тихо повернуті до вільнішої межі. Обидві валідні, тож
        # жодна перевірка відношень цього не побачить — лише розрізняльний випадок.
        "M602_THE_DEPLOYMENT_GATE_SILENTLY_REVERTS_TO_THE_LOOSE_BOUND",
        "apps/api/src/korpus/application/calibration.py",
        "        return clopper_pearson_upper_bound(",
        "        return hoeffding_upper_bound(",
        (
            "apps/api/tests/test_exact_risk_bound.py::"
            "test_the_deployment_gate_reads_the_exact_bound_and_not_the_loose_one",
        ),
    ),
    Mutant(
        # Виробник, що завжди свіжий. Перевірка лишається зеленою рівно в тому стані,
        # заради якого існує, — і мовчить про дерево, якого звіт не міряв.
        "M603_A_STALE_PRODUCER_REPORTS_AS_FRESH",
        "scripts/check_evidence_freshness.py",
        '    return ("СВІЖИЙ" if claimed == expected else "ПРО ІНШЕ ДЕРЕВО"), claimed[:16]',
        '    return "СВІЖИЙ", claimed[:16]',
        (
            "apps/api/tests/test_evidence_freshness.py::"
            "test_a_producer_that_measured_another_tree_is_named_with_its_target",
        ),
    ),
    Mutant(
        # Споживач, сліпий до зсуву власних входів: джерело те саме, судив інші байти.
        # Саме цю причину `snapshot` називає словами про «інший файл».
        "M604_A_CONSUMER_IGNORES_THAT_ITS_INPUTS_MOVED",
        "scripts/check_evidence_freshness.py",
        '    return ("СВІЖИЙ" if not moved else "СУДИВ ІНШІ ФАЙЛИ"), sorted(moved)',
        '    return "СВІЖИЙ", sorted(moved)',
        (
            "apps/api/tests/test_evidence_freshness.py::"
            "test_a_consumer_is_stale_when_an_input_moved_even_though_the_tree_did_not",
        ),
    ),
    Mutant(
        # UNKNOWN, прочитаний як PASS: звіт без походження не каже, про яке він дерево,
        # і саме тому не сміє рахуватись свіжим.
        "M605_EVIDENCE_WITHOUT_PROVENANCE_COUNTS_AS_FRESH",
        "scripts/check_evidence_freshness.py",
        '        return "БЕЗ ПОХОДЖЕННЯ", ""',
        '        return "СВІЖИЙ", ""',
        (
            "apps/api/tests/test_evidence_freshness.py::"
            "test_a_report_without_provenance_is_not_read_as_fresh",
        ),
    ),
    Mutant(
        # Найтихіший спосіб дістати гарну оцінку ранжування: рахувати лише те, що
        # вдалось. Тоді КОЖЕН провал добору піднімає число, і воно росте від поломки.
        "M606_A_RETRIEVAL_FAILURE_RAISES_THE_RANKING_SCORE",
        "scripts/measure_ranking_quality.py",
        "    reachable_share = metrics.evaluated_queries / total",
        "    reachable_share = 1.0",
        (
            "apps/api/tests/test_ranking_quality_driver.py::"
            "test_the_whole_set_average_is_depressed_by_an_unreachable_query",
        ),
    ),
    Mutant(
        # Стеля, що завжди одиниця. Тоді Recall@20 = 0.52 читається як зламаний
        # ранжувальник, хоча середній ДОСЯЖНИЙ максимум за міткою — 0.82.
        "M607_THE_LABELLING_CEILING_DISAPPEARS_FROM_THE_REPORT",
        "scripts/measure_ranking_quality.py",
        "    return 1.0 if relevant_in_pool <= cutoff else cutoff / relevant_in_pool",
        "    return 1.0",
        (
            "apps/api/tests/test_ranking_quality_driver.py::"
            "test_the_recall_ceiling_is_twenty_over_the_relevant_count",
        ),
    ),
    Mutant(
        # Провал добору, знятий з обліку: список порожній, знаменник цілий, і різниця
        # між «не знайшли» та «знайшли й погано впорядкували» зникає.
        "M608_A_QUERY_WITH_NO_RELEVANT_CANDIDATE_IS_NOT_RECORDED",
        "scripts/measure_ranking_quality.py",
        '            unreachable.append(str(case["id"]))',
        "            pass",
        (
            "apps/api/tests/test_ranking_quality_driver.py::"
            "test_a_query_whose_pool_holds_nothing_relevant_is_counted_not_dropped",
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
        "LINEAGE",
    )
    shutil.copytree(ROOT, destination, ignore=ignored, dirs_exist_ok=True)


MUTATION_ORCHESTRATION_ENV = frozenset({"KORPUS_MUTATION_JOBS", "KORPUS_MUTATION_SHARDS"})


def mutation_test_environment(*, pythonpath: Path) -> dict[str, str]:
    """Environment seen by the application under mutation.

    Mutation orchestration controls are intentionally removed.  They belong to the
    harness, not to KORPUS runtime configuration; leaking them into the app once made
    every mutant appear killed because startup rejected an unknown KORPUS_* variable.
    """
    environment = os.environ.copy()
    for name in MUTATION_ORCHESTRATION_ENV:
        environment.pop(name, None)
    environment["PYTHONPATH"] = str(pythonpath)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONHASHSEED"] = "0"
    return environment


def _prepare_mutant_sandbox(temp: str, mutant: Mutant) -> tuple[Path, Path, Path, bool]:
    sandbox = Path(temp) / "repo"
    api_overlay = mutant.file.startswith("apps/api/src/") and not mutant.full_copy
    if api_overlay:
        source_root = Path(temp) / "api-src"
        shutil.copytree(ROOT / "apps/api/src", source_root)
        target = source_root / Path(mutant.file).relative_to("apps/api/src")
        return target, source_root, ROOT, True
    copy_repository(sandbox)
    source_root = sandbox / "apps/api/src"
    return sandbox / mutant.file, source_root, sandbox, False


def _mutation_status_from_pytest_exit(returncode: int) -> str:
    """Map pytest exit codes without crediting collection/bootstrap errors as kills."""
    if returncode == 0:
        return "SURVIVED"
    if returncode == 1:
        return "KILLED"
    return "ERROR"


def run_mutant(mutant: Mutant) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"korpus-{mutant.id.lower()}-") as temp:
        target, source_root, cwd, api_overlay = _prepare_mutant_sandbox(temp, mutant)
        original = target.read_text(encoding="utf-8")
        count = original.count(mutant.old)
        if count != 1:
            return {
                "id": mutant.id,
                "file": mutant.file,
                "status": "INVALID",
                "target_occurrences": count,
                "reason": "mutation target must occur exactly once",
                "tests": list(mutant.tests),
                "sandbox_mode": "api_source_overlay" if api_overlay else "full_copy",
            }
        target.write_text(original.replace(mutant.old, mutant.new), encoding="utf-8")
        environment = mutation_test_environment(pythonpath=source_root)
        command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--maxfail=1"]
        if api_overlay:
            command += ["-o", f"pythonpath={source_root}"]
        command += list(mutant.tests)
        returncode, stdout, stderr, timed_out, termination = run_bounded(
            command, cwd=cwd, env=environment, timeout_seconds=45
        )
        output = stdout + ("\n" + stderr if stderr else "")
        mode = "api_source_overlay" if api_overlay else "full_copy"
        # `returncode is None` приходить рівно з таймауту (process_tree_runtime:65), але
        # інваріант жив у голові, а не в типі. Названий тут — і тоді «убитий аварією» не
        # може тихо стати статусом, порахованим із None.
        if timed_out or returncode is None:
            return {
                "id": mutant.id,
                "file": mutant.file,
                "status": "ERROR",
                "reason": "pytest_timeout",
                "termination": termination,
                "target_occurrences": count,
                "tests": list(mutant.tests),
                "sandbox_mode": mode,
                "output_tail": output[-3000:],
            }
        status = _mutation_status_from_pytest_exit(returncode)
        return {
            "id": mutant.id,
            "file": mutant.file,
            "status": status,
            "returncode": returncode,
            "target_occurrences": count,
            "tests": list(mutant.tests),
            "sandbox_mode": mode,
            "output_tail": output[-3000:],
            **({"reason": f"pytest_exit_{returncode}"} if status == "ERROR" else {}),
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
        "errors": [result["id"] for result in results if result["status"] == "ERROR"],
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


def verify_mutation_baseline(mutants: list[Mutant]) -> None:
    """Prove the focused tests pass before any mutation is applied.

    A pre-existing failure must never be credited as a mutant kill.  Each shard checks
    the union of tests it will use once, under the same cleaned environment as mutants.
    """
    tests = list(dict.fromkeys(spec for mutant in mutants for spec in mutant.tests))
    if not tests:
        return
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-q",
        "--maxfail=1",
        *tests,
    ]
    returncode, stdout, stderr, timed_out, termination = run_bounded(
        command,
        cwd=ROOT,
        env=mutation_test_environment(pythonpath=ROOT / "apps/api/src"),
        timeout_seconds=300,
    )
    output = stdout + ("\n" + stderr if stderr else "")
    if timed_out:
        raise RuntimeError(
            "mutation baseline timed out; refusing to execute mutants "
            f"({termination})\n" + output[-6000:]
        )
    if returncode != 0:
        raise RuntimeError(
            "mutation baseline is not green; refusing to credit non-zero mutant exits\n"
            + output[-6000:]
        )


def run_selected(mutants: list[Mutant], jobs: int) -> list[dict[str, object]]:
    """Run mutants, preserving catalogue order in the results regardless of jobs.

    Each mutant already works in its own copy of the tree, so concurrency changes
    wall-clock and nothing else. Order is restored explicitly because a report whose
    contents depend on scheduling cannot be compared between runs.
    """

    verify_mutation_baseline(mutants)
    if jobs <= 1:
        return [run_mutant(mutant) for mutant in mutants]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(run_mutant, mutants))


def _write_report(report: dict[str, object], output: Path, *, portable: bool = False) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    output.write_text(serialized, encoding="utf-8")
    if portable:
        portable_output = ROOT / "reports/MUTATION_FULL_CATALOGUE_CURRENT.json"
        portable_output.parent.mkdir(parents=True, exist_ok=True)
        portable_output.write_text(serialized, encoding="utf-8")


def _print_summary(report: dict[str, object]) -> None:
    summary = {key: value for key, value in report.items() if key != "results"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _run_probe(only: str, jobs: int) -> int:
    requested = [name.strip() for name in only.split(",") if name.strip()]
    by_id = {mutant.id: mutant for mutant in MUTANTS}
    unknown = [name for name in requested if name not in by_id]
    if unknown:
        raise SystemExit(f"unknown mutant ids: {unknown}")
    results = run_selected([by_id[name] for name in requested], jobs)
    report = summarize(results, shard_index=None, shard_count=1)
    report["probe"] = True
    _write_report(report, ROOT / "var/mutation-probe.json")
    _print_summary(report)
    return 0 if report["mutation_score"] == 1.0 else 1


def _run_catalogue(args: argparse.Namespace) -> tuple[dict[str, object], Path]:
    if args.merge:
        return merge_shards(args.shard_count), ROOT / "var/mutation-report.json"
    shard_index = 0 if args.shard_index is None else args.shard_index
    if not 0 <= shard_index < args.shard_count:
        raise SystemExit("--shard-index must satisfy 0 <= index < shard-count")
    selected = list(MUTANTS[shard_index :: args.shard_count])
    results = run_selected(selected, args.jobs)
    report = summarize(
        results,
        shard_index=shard_index if args.shard_count > 1 else None,
        shard_count=args.shard_count,
    )
    if args.shard_count > 1:
        shard_name = f"shard-{shard_index}-of-{args.shard_count}.json"
        return report, ROOT / "var/mutation-shards" / shard_name
    return report, ROOT / "var/mutation-report.json"


def main() -> int:
    args = parse_args()
    if args.shard_count < 1:
        raise SystemExit("--shard-count must be >= 1")
    if args.jobs < 1:
        raise SystemExit("--jobs must be >= 1")
    if args.only:
        return _run_probe(args.only, args.jobs)

    report, output = _run_catalogue(args)
    _write_report(report, output, portable=args.merge)
    _print_summary(report)
    results = report["results"]
    counted = len(results) if isinstance(results, (list, tuple)) else 0
    expected = len(MUTANTS) if args.merge or args.shard_count == 1 else counted
    return 0 if report["mutation_score"] == 1.0 and report["valid_mutants"] == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
