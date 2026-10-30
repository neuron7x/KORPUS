"""Fail-closed proof that each mandatory PostgreSQL security pytest node executed."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

# Frozen at the audited SHA; edits to security tests require an explicit contract update.
EXPECTED_TESTS: dict[str, tuple[str, ...]] = {
    "test_postgres_role_grants": (
        "test_every_application_table_is_granted_to_the_application_role",
        "test_no_grant_names_a_table_that_does_not_exist",
        "test_a_table_is_classified_exactly_once",
    ),
    "test_repository_access_refusals": (
        "test_an_entitled_identity_reads_the_document",
        "test_listing_hides_documents_from_a_corpus_the_identity_does_not_hold",
        "test_get_document_returns_the_row_and_leaves_the_decision_to_the_caller",
        "test_a_document_that_does_not_exist_is_absent_rather_than_an_error",
        "test_near_duplicate_search_is_scoped_to_the_corpora_the_identity_holds",
        "test_near_duplicate_search_finds_the_version_for_an_entitled_identity",
        "test_a_malformed_fingerprint_is_refused",
        "test_a_similarity_threshold_outside_the_supported_range_is_refused",
        "test_identical_bytes_under_a_different_revision_are_a_different_version",
        "test_a_hash_lookup_is_scoped_to_the_document_when_one_is_given",
        "test_a_hash_lookup_is_scoped_to_the_corpus_when_one_is_given",
        "test_bytes_nobody_uploaded_are_not_found",
        "test_a_reviewer_cannot_transition_a_version_from_another_corpus",
        "test_a_version_cannot_be_queued_against_a_document_in_another_corpus",
        "test_listing_hides_a_document_above_the_readers_clearance",
    ),
    "test_tenancy_threats": (
        "test_t01_a_forged_billing_event_cannot_activate_a_plan",
        "test_t02_a_replayed_event_is_a_duplicate_and_an_old_one_is_refused",
        "test_t03_a_canceled_subscription_cannot_be_resurrected",
        "test_t04_no_request_field_can_assert_that_a_subscription_is_paid",
        "test_t05_a_plan_cannot_escalate_beyond_the_identity",
        "test_t06_another_accounts_conversation_is_unreachable_by_id",
        "test_t07_a_foreign_id_and_a_nonexistent_id_are_indistinguishable",
        "test_t08_disabling_takes_effect_on_the_next_request_not_the_next_login",
        "test_t09_an_identity_provider_cannot_grant_corpora_through_a_claim",
        "test_t10_a_prior_answer_is_stored_as_an_answer_and_not_as_a_source",
        "test_t11_a_restricted_deployment_does_not_send_the_question_anywhere",
        "test_t12_an_unbounded_webhook_body_is_refused_before_it_is_parsed",
        "test_every_named_threat_class_has_a_test",
        "test_a_denial_is_not_a_silent_pass",
        "test_t12a_declared_oversize_is_refused_before_stream_consumption",
        "test_t12b_chunked_oversize_stops_at_the_first_excess_chunk",
    ),
    "test_audit": (
        "test_audit_chain_and_external_anchor_verify",
        "test_audit_chain_detects_payload_tampering",
        "test_audit_anchor_detects_tail_truncation",
        "test_audit_anchor_detects_file_tampering",
        "test_concurrent_audit_appends_form_one_total_order",
        "test_audit_chain_rejects_re_signed_broken_predecessor_link",
        "test_committed_audit_anchor_failure_is_recoverable_without_replaying_event",
    ),
    "test_postgres_rls_claim_forgery": (
        "test_session_settings_cannot_raise_the_readers_own_clearance",
        "test_the_application_login_cannot_touch_the_context_table",
        "test_the_application_login_cannot_call_the_broker",
        "test_the_authorized_flow_still_sees_what_it_may",
    ),
    "test_postgres_rls_claim_mutations": (
        "test_each_app_owned_session_claim_is_ignored_by_broker",
        "test_forged_claims_cannot_change_hidden_document",
        "test_forged_claims_cannot_insert_a_restricted_document",
        "test_review_login_cannot_forge_broker_bound_claims",
        "test_review_login_cannot_mutate_non_review_document_columns",
        "test_review_login_cannot_call_the_authorization_broker",
        "test_pooled_session_cannot_reuse_a_privileged_binding_or_session_forgery",
    ),
    "test_postgres_rls_policy_state": (
        "test_every_protected_table_has_rls_enabled_and_forced",
        "test_no_policy_still_consumes_a_caller_settable_claim",
        "test_the_application_login_cannot_disable_or_rewrite_a_policy",
        "test_the_broker_login_has_no_privilege_on_the_protected_data_plane",
        "test_security_definer_routines_keep_a_hardened_search_path",
        "test_the_application_login_may_execute_readers_but_never_the_binder",
    ),
    "test_postgres_role_reprovision_boundary": (
        "test_reprovision_destroys_drift_on_every_runtime_login",
        "test_no_runtime_login_keeps_a_grant_on_the_binding_table",
        "test_runtime_logins_may_connect_and_use_but_never_create",
    ),
    "test_postgres_approval_provenance": (
        "test_the_application_login_cannot_write_a_reviewer_decision",
        "test_the_review_login_can_write_exactly_those_columns",
        "test_the_application_login_keeps_what_is_its_own",
        "test_the_document_tier_belongs_to_the_approver_not_to_the_submitter",
        "test_the_application_login_cannot_give_birth_to_a_reviewed_version",
        "test_the_schema_owner_is_not_blocked_by_the_runtime_guard",
        "test_the_marker_group_grants_nothing_by_itself",
    ),
    "test_postgres_integration": (
        "test_postgres_migrated_search_rls_access_and_audit",
    ),
}
EXPECTED_CASES = 111
REPORT = Path("var/postgres-security/pytest-junit.xml")


def inspect_pytest_junit(root: Path) -> tuple[bool, int, list[str]]:
    """Require fresh, unique, non-skipped executions, not merely existing test files."""
    try:
        cases = ElementTree.parse(root / REPORT).findall(".//testcase")
    except (OSError, ElementTree.ParseError):
        return False, 0, ["missing_or_invalid_junit"]
    seen: set[tuple[str, str]] = set()
    functions: set[tuple[str, str]] = set()
    invalid = False
    for case in cases:
        module = case.attrib.get("classname", "").rsplit(".", 1)[-1]
        name = case.attrib.get("name", "")
        node = (module, name)
        if node in seen or not name.startswith("test_") or any(
            case.find(tag) is not None for tag in ("skipped", "failure", "error")
        ):
            invalid = True
        seen.add(node)
        functions.add((module, name.split("[", 1)[0]))
    missing = sorted(
        f"{module}::{name}"
        for module, names in EXPECTED_TESTS.items()
        for name in names
        if (module, name) not in functions
    )
    return len(cases) == EXPECTED_CASES and not invalid and not missing, len(cases), missing
