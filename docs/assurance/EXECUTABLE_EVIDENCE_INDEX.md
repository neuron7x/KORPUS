# Executable evidence index v1

- Source Python modules: **137**
- Test modules: **175**
- Test functions statically discovered: **1237**
- Direct test→source import edges: **359**

This is a static traceability index. It does not claim a test proves every imported module behavior; it makes the executable surface reviewable and byte-addressable.

## `apps/api/tests/test_access_control.py`

- SHA-256: `81192dd9879aea09897de4c0cf59c14a80d78b7483aa4dd4b5d0d49fe6c9e0b5`
- Lines: 116
- Tests: 5
- KORPUS imports: none

Test predicates:
- `test_access_is_monotone_in_clearance`
- `test_access_tier_is_enforced_in_repository_even_for_public_classification`
- `test_public_identity_cannot_request_restricted_corpus`
- `test_restricted_corpus_update_does_not_change_public_release`
- `test_restricted_document_never_enters_public_retrieval`

## `apps/api/tests/test_access_oracles.py`

- SHA-256: `6695aa7e2e9534c0f981d5bfd50572385fdce2e3bd091555c5c8f202bde307b9`
- Lines: 373
- Tests: 6
- KORPUS imports: `korpus.application.ingestion`, `korpus.application.policy`, `korpus.composition`, `korpus.config`, `korpus.domain.models`, `korpus.infrastructure.object_store`, `korpus.main`, `korpus.security.auth`

Test predicates:
- `test_an_unentitled_reviewer_cannot_take_an_order_out_of_force`
- `test_the_entitled_reviewer_can_still_rescind`
- `test_the_exact_duplicate_check_does_not_confirm_unreadable_content`
- `test_the_near_duplicate_probe_is_not_a_graded_content_oracle`
- `test_the_near_duplicate_probe_still_finds_a_duplicate_the_caller_may_see`
- `test_the_outsider_cannot_see_the_document_at_all`

## `apps/api/tests/test_account_administration.py`

- SHA-256: `f45d7a2e19e637de348d2b53e4a922b191490091a9e3ca1b03f4578d6539a7f5`
- Lines: 318
- Tests: 14
- KORPUS imports: `korpus.config`, `korpus.domain.models`, `korpus.infrastructure.repository`, `korpus.main`, `korpus.security.auth`

Test predicates:
- `test_a_disabled_administrator_cannot_administer`
- `test_a_reason_short_enough_to_be_meaningless_is_refused`
- `test_an_administrator_cannot_disable_the_account_they_are_using`
- `test_an_administrator_may_still_re_enable_themselves`
- `test_an_operator_can_disable_an_account_without_a_database_shell`
- `test_an_operator_can_find_the_account_by_the_subject_they_were_given`
- `test_an_unknown_account_is_a_404_not_a_500`
- `test_an_unknown_status_is_refused_by_the_contract`
- `test_being_switched_off_and_not_being_an_admin_are_different_answers`
- `test_listing_and_lookup_are_administrator_only`
- `test_only_an_administrator_may_switch_a_person_off`
- `test_the_change_reaches_the_audit_chain_with_its_reason`
- `test_the_listing_can_answer_whether_it_is_actually_off`
- `test_the_same_operator_can_put_it_back`

## `apps/api/tests/test_account_domain.py`

- SHA-256: `49a1fc0ead95774a09ea4eb2f0d4d960c0d83b8cd3fe9f043e7327a1f1d901bb`
- Lines: 217
- Tests: 11
- KORPUS imports: `korpus.application.accounts`, `korpus.application.tenancy_ports`, `korpus.domain.tenancy`, `korpus.infrastructure.repository`, `korpus.infrastructure.tenancy_schema`

Test predicates:
- `test_a_disabled_account_cannot_use_protected_functionality`
- `test_a_first_login_creates_exactly_one_account`
- `test_account_creation_writes_its_audit_event_in_the_same_commit`
- `test_an_account_record_carries_no_authorization_field`
- `test_an_unknown_account_is_a_refusal_not_none`
- `test_claims_without_a_subject_are_refused`
- `test_concurrent_first_logins_converge_on_one_account`
- `test_disabling_requires_a_reason`
- `test_identity_claims_carrying_authorization_are_refused_not_filtered`
- `test_re_enabling_clears_the_disabled_timestamp`
- `test_the_profile_keeps_only_what_a_person_recognises_themselves_by`

## `apps/api/tests/test_admission_cannot_be_self_granted.py`

- SHA-256: `f4bbbd1e70ecc2dfd52694a6ff785d656876b59a1c28003c1496513ef8eac3a6`
- Lines: 250
- Tests: 8
- KORPUS imports: `korpus.application.admission`, `korpus.security.attestors`

Test predicates:
- `test_a_correctly_attested_ground_is_accepted`
- `test_an_attestation_naming_a_document_that_does_not_exist_is_refused`
- `test_an_attestation_signed_in_the_future_is_refused`
- `test_an_attestation_whose_digest_does_not_match_the_document_is_refused`
- `test_an_independent_assessment_signed_by_the_engineering_owner_is_refused`
- `test_an_unparseable_signature_date_is_refused`
- `test_clearing_every_ground_with_forged_attestations_still_withholds`
- `test_the_shipped_register_still_withholds`

## `apps/api/tests/test_admission_register.py`

- SHA-256: `ce34be9d7fe7ba6f2f8b4e9efd9dffabd539f76214d5690245f4890663893a84`
- Lines: 198
- Tests: 8
- KORPUS imports: `korpus.application.admission`

Test predicates:
- `test_a_ground_cleared_with_a_test_that_does_not_exist_is_refused`
- `test_a_ground_cleared_with_no_evidence_at_all_is_refused`
- `test_an_external_ground_cannot_be_cleared_by_editing_the_register`
- `test_an_external_ground_with_a_complete_attestation_is_accepted`
- `test_an_incomplete_attestation_is_refused`
- `test_every_ground_the_register_clears_cites_evidence_that_exists`
- `test_the_shipped_register_withholds_and_says_why`
- `test_the_verdict_can_be_true_when_every_ground_is_properly_cleared`

## `apps/api/tests/test_anchor_delivery_backlog.py`

- SHA-256: `5fce28926c37b3968b41722139713938ab056c6169c7b368f949b327d74465ad`
- Lines: 82
- Tests: 3
- KORPUS imports: `korpus.domain.models`

Test predicates:
- `test_an_empty_outbox_delivers_nothing`
- `test_delivery_reports_how_many_checkpoints_it_closed`
- `test_one_pass_clears_a_backlog_larger_than_the_batch`

## `apps/api/tests/test_answer_composition.py`

- SHA-256: `d6dc2c69ff376575be03317f845ff100f92dcfdc03da273facddcf09e68d3311`
- Lines: 129
- Tests: 11
- KORPUS imports: `korpus.application.composition`

Test predicates:
- `test_a_composer_that_fails_leaves_the_extract_untouched`
- `test_adding_a_sentence_nobody_retrieved_is_refused`
- `test_an_opening_longer_than_a_line_is_refused`
- `test_an_opening_made_of_words_in_the_evidence_is_admitted`
- `test_an_opening_that_introduces_a_negation_is_refused`
- `test_an_opening_that_states_a_number_is_refused`
- `test_an_opening_that_states_something_the_evidence_does_not_is_refused`
- `test_dropping_a_retrieved_sentence_is_refused`
- `test_no_composer_is_the_same_as_a_composer_that_says_nothing`
- `test_reordering_is_allowed_because_it_invents_nothing`
- `test_the_gate_checks_against_what_the_reader_is_shown`

## `apps/api/tests/test_answer_paths_are_bounded.py`

- SHA-256: `63cd5fb1601eac6c116586485e6eb2b34e892a31542a61c4097e64546176837b`
- Lines: 121
- Tests: 4
- KORPUS imports: none

Test predicates:
- `test_both_named_routes_are_present_and_bounded`
- `test_every_answer_path_goes_through_the_shared_bound`
- `test_the_bound_lives_in_exactly_one_module`
- `test_this_check_can_fail`

## `apps/api/tests/test_answers.py`

- SHA-256: `51923d8e8ddadf597534e0446eb70be00adf061cc28176762d3cd6322be9e92c`
- Lines: 231
- Tests: 11
- KORPUS imports: `korpus.application.answer_query`, `korpus.application.retrieval`, `korpus.domain.models`, `korpus.infrastructure.repository`

Test predicates:
- `test_a_declaration_with_control_characters_is_refused`
- `test_a_query_without_a_declaration_records_its_absence`
- `test_a_retrieval_deadline_abstains_rather_than_answering_from_a_partial_search`
- `test_answer_is_bitwise_deterministic_except_generated_metadata`
- `test_approved_document_produces_exact_claim_bound_citation`
- `test_instruction_like_source_sentence_is_never_emitted`
- `test_partial_support_is_not_reported_as_full_coverage`
- `test_query_control_injection_abstains_before_retrieval`
- `test_required_retrieval_dependency_outage_abstains_fail_closed`
- `test_the_operator_declaration_enters_the_audit_chain_marked_unverified`
- `test_unapproved_document_cannot_answer`

## `apps/api/tests/test_api_contract.py`

- SHA-256: `c3f88bd84b4d9b04980b2f524fcba048c38a1f68edc7762bd5ea79f7071377a2`
- Lines: 24
- Tests: 2
- KORPUS imports: none

Test predicates:
- `test_openapi_contract_cli_runs_with_make_pythonpath`
- `test_openapi_contract_has_no_unreviewed_drift`

## `apps/api/tests/test_architecture.py`

- SHA-256: `c209c50b5c39eed9bcc505d2f632c4110afbd734901363b6528670bef1212aee`
- Lines: 368
- Tests: 10
- KORPUS imports: `korpus.application`, `korpus.composition`, `korpus.domain`, `korpus.domain.models`, `korpus.infrastructure.extraction`, `korpus.infrastructure.ingestion_jobs`, `korpus.infrastructure.object_store`, `korpus.infrastructure.repository`

Test predicates:
- `test_every_model_that_leaves_the_process_is_frozen`
- `test_every_port_the_application_declares_has_an_implementation`
- `test_no_layer_imports_a_layer_above_it`
- `test_no_public_function_takes_a_positional_boolean_flag`
- `test_the_answer_cannot_be_edited_after_the_policy_decided_it`
- `test_the_application_layer_reaches_infrastructure_only_through_ports`
- `test_the_citation_hash_has_the_same_shape_as_the_version_it_points_at`
- `test_the_composition_root_is_the_only_module_naming_both_sides`
- `test_the_domain_depends_on_nothing_in_this_package`
- `test_the_layering_check_can_fail`

## `apps/api/tests/test_assurance_aggregation.py`

- SHA-256: `2e29037dd4c681e5ebdc0487fbb5bef0c397b443b960c4ea245be8febfadc236`
- Lines: 195
- Tests: 14
- KORPUS imports: `korpus.application.assurance`, `korpus.application.provenance`

Test predicates:
- `test_a_quality_tool_that_did_not_pass_fails_the_aggregate`
- `test_a_suite_that_skipped_almost_everything_is_not_a_run`
- `test_a_tool_reporting_pass_with_a_nonzero_exit_code_is_rejected`
- `test_absent_quality_evidence_is_a_failure_not_a_pass`
- `test_complete_evidence_reaches_pass`
- `test_coverage_below_policy_fails`
- `test_declared_but_unexecuted_tooling_cannot_pass`
- `test_errored_tests_fail_the_aggregate`
- `test_evidence_from_a_foreign_tree_fails_the_aggregate`
- `test_failing_tests_fail_the_aggregate`
- `test_missing_gate_reports_fail_the_aggregate`
- `test_mutation_score_over_catalogue_is_the_measured_quantity`
- `test_unparsable_test_count_is_not_treated_as_success`
- `test_zero_tests_is_not_a_successful_run`

## `apps/api/tests/test_assurance_calculus.py`

- SHA-256: `bb6dea24020e4d4bc8d132d50ed8443d36fb3366e6c0a0dd83dafd8cd0e821d0`
- Lines: 216
- Tests: 13
- KORPUS imports: `korpus.application.assurance_calculus`

Test predicates:
- `test_conflicting_evidence_join_fails_closed`
- `test_evidence_class_cannot_claim_execution_without_execution`
- `test_evidence_join_refuses_cross_source_aggregation`
- `test_high_weighted_score_cannot_compensate_for_missing_mandatory_gate`
- `test_independent_attested_redteam_can_close_its_gate`
- `test_maximum_single_dimension_effect_is_exactly_weight_times_100`
- `test_policy_refuses_weights_that_do_not_sum_to_one`
- `test_release_binding_is_required_even_for_independent_attestation`
- `test_stale_dimension_evidence_contributes_zero`
- `test_stronger_same_identity_evidence_dominates_weaker`
- `test_unexecuted_evidence_caps_dimension_even_when_claimed_score_is_100`
- `test_weighted_score_is_bounded_for_every_corner_of_the_hypercube`
- `test_weighted_score_refuses_wrong_arity_and_out_of_range_values`

## `apps/api/tests/test_assurance_trust.py`

- SHA-256: `8ba51eb8dc6a330e4b9107818b639a848e9dea670547416a30f2250c36d9bcaf`
- Lines: 52
- Tests: 5
- KORPUS imports: `korpus.application.assurance_trust`

Test predicates:
- `test_empty_runtime_trust_does_not_create_trust`
- `test_invalid_runtime_trust_root_fails_closed`
- `test_runtime_trust_root_can_be_injected_without_mutating_source`
- `test_runtime_trust_root_is_admitted_on_protected_ci`
- `test_runtime_trust_root_is_refused_on_unprotected_ci`

## `apps/api/tests/test_attestation_signatures.py`

- SHA-256: `b8dc29c9dfaa09732d067be95f804823c95dc9996f14b8950670c00ad555598a`
- Lines: 259
- Tests: 13
- KORPUS imports: `korpus.application.admission`, `korpus.security.attestors`

Test predicates:
- `test_a_corpus_owner_cannot_sign_the_independent_assessment`
- `test_a_correctly_signed_attestation_verifies`
- `test_a_key_of_the_wrong_length_cannot_be_enrolled`
- `test_a_signature_from_a_revoked_key_is_refused`
- `test_a_signature_from_an_unenrolled_key_is_refused`
- `test_a_signature_obtained_for_another_ground_cannot_be_moved`
- `test_a_signature_outside_the_key_validity_window_is_refused`
- `test_a_signature_over_a_different_document_is_refused`
- `test_altering_the_signer_name_after_signing_is_refused`
- `test_an_assessor_key_may_sign_a_measurement`
- `test_an_unknown_role_cannot_be_enrolled`
- `test_an_unsigned_attestation_is_refused`
- `test_the_admission_verdict_refuses_a_clearance_with_no_signature`

## `apps/api/tests/test_attested_evidence.py`

- SHA-256: `ab469aa45d57773c2751d29b4d5671c72c67ddc98ebcd89cab3ce5ad92cc53fa`
- Lines: 77
- Tests: 4
- KORPUS imports: `korpus.application.attested_evidence`

Test predicates:
- `test_attestation_cannot_be_replayed_for_another_release_or_filename`
- `test_tampered_evidence_breaks_signature_and_digest_binding`
- `test_valid_but_untrusted_self_signature_is_not_trust_evidence`
- `test_valid_signature_from_pretrusted_key_is_admitted`

## `apps/api/tests/test_audit.py`

- SHA-256: `f7c1bc80fd80c8bee6ebf2b5834983e6f9f5344542578121ad2c73455da59595`
- Lines: 145
- Tests: 7
- KORPUS imports: `korpus.infrastructure.audit_anchor`, `korpus.infrastructure.repository`

Test predicates:
- `test_audit_anchor_detects_file_tampering`
- `test_audit_anchor_detects_tail_truncation`
- `test_audit_chain_and_external_anchor_verify`
- `test_audit_chain_detects_payload_tampering`
- `test_audit_chain_rejects_re_signed_broken_predecessor_link`
- `test_committed_audit_anchor_failure_is_recoverable_without_replaying_event`
- `test_concurrent_audit_appends_form_one_total_order`

## `apps/api/tests/test_audit_anchor_semantics.py`

- SHA-256: `5910dc457b43af8d4c9f12526149202b465e8962a432a00c0c5b76de4994f8d5`
- Lines: 108
- Tests: 5
- KORPUS imports: `korpus.domain.models`

Test predicates:
- `test_a_burst_of_appends_leaves_the_chain_valid`
- `test_an_anchor_ahead_of_the_head_is_invalid`
- `test_an_anchor_behind_the_head_is_pending_not_invalid`
- `test_an_anchor_that_disagrees_at_its_own_position_is_invalid`
- `test_the_verification_endpoint_reports_pending_delivery`

## `apps/api/tests/test_audit_export.py`

- SHA-256: `0b96ff45b60909a98782b468bbc3bca7624153da98788da6ad0a134452b75945`
- Lines: 166
- Tests: 13
- KORPUS imports: `korpus.application.audit_export`

Test predicates:
- `test_a_batch_that_skips_the_cursor_is_refused`
- `test_a_broken_link_is_refused_even_when_the_sequences_are_consecutive`
- `test_a_continuous_batch_is_accepted`
- `test_a_sequence_gap_inside_the_batch_is_refused`
- `test_an_empty_batch_has_no_cursor_to_advance_to`
- `test_an_empty_batch_is_not_an_error`
- `test_jsonl_is_one_event_per_line`
- `test_payloads_are_excluded_unless_asked_for`
- `test_payloads_travel_only_when_explicitly_included`
- `test_the_batch_digest_changes_when_any_event_changes`
- `test_the_manifest_carries_the_cursor_the_collector_asks_with_next`
- `test_the_manifest_states_what_the_hmac_link_does_not_prove`
- `test_the_payload_digest_does_not_depend_on_stored_key_order`

## `apps/api/tests/test_audit_key_rotation.py`

- SHA-256: `9ae356e3902bd01e5873f2ac4390cf8beadf4508695bb7a36e2368c13fee4ef1`
- Lines: 178
- Tests: 10
- KORPUS imports: `korpus.application.keyring`, `korpus.application.policy`, `korpus.domain.models`, `korpus.infrastructure.repository`

Test predicates:
- `test_a_chain_opened_without_the_previous_key_does_not_verify`
- `test_a_key_id_that_is_unsafe_in_a_row_or_a_command_is_refused`
- `test_a_revoked_key_cannot_be_the_active_one`
- `test_a_revoked_key_still_verifies_and_is_reported_as_revoked`
- `test_an_active_key_outside_the_ring_is_refused`
- `test_an_event_naming_an_unknown_key_is_invalid`
- `test_events_signed_before_a_rotation_still_verify`
- `test_events_written_before_key_ids_existed_are_attributed_not_orphaned`
- `test_the_chain_written_under_one_key_verifies_after_rotating_to_another`
- `test_the_new_key_signs_and_the_old_one_no_longer_can`

## `apps/api/tests/test_audit_names_governing_version.py`

- SHA-256: `bb3c88e4f3d0ee7e49a789e65f423ce1c1798080396332d96fa0186fe898b108`
- Lines: 98
- Tests: 4
- KORPUS imports: none

Test predicates:
- `test_an_abstention_records_the_same_fields`
- `test_the_event_names_the_version_and_span_the_answer_stood_on`
- `test_the_event_records_the_date_the_answer_was_given_for`
- `test_the_event_records_the_thresholds_that_were_applied`

## `apps/api/tests/test_audit_reader_seam.py`

- SHA-256: `7959511a649e5ec6001d59457ccceb0f5447a48a030f5456c0528769ec49e030`
- Lines: 131
- Tests: 5
- KORPUS imports: `korpus.application.policy`, `korpus.domain.models`, `korpus.infrastructure`, `korpus.infrastructure.audit_reader`, `korpus.infrastructure.repository`

Test predicates:
- `test_a_tampered_event_is_caught_across_the_seam`
- `test_events_written_through_the_repository_verify_through_the_reader`
- `test_readiness_reports_the_schema_revision_the_migrations_declare`
- `test_the_reader_opens_its_own_connections`
- `test_the_writer_and_the_verifier_share_one_canonical_form`

## `apps/api/tests/test_auth.py`

- SHA-256: `94b6c1ab391a0249da328eebbd72055f4814b91abb2a8b00b166f86e2a0e3a74`
- Lines: 153
- Tests: 8
- KORPUS imports: `korpus.config`, `korpus.domain.models`, `korpus.main`, `korpus.security.auth`

Test predicates:
- `test_controlled_environment_requires_migration_managed_schema`
- `test_controlled_environment_requires_oidc`
- `test_controlled_environment_requires_remote_audit_anchor`
- `test_jwt_auth_rejects_expired_wrong_audience_and_overlong_lifetime`
- `test_local_jwt_rejects_weak_secret`
- `test_query_contract_has_no_client_controlled_clearance`
- `test_secret_files_are_resolved`
- `test_signed_token_contains_server_verified_identity`

## `apps/api/tests/test_authority_ranking.py`

- SHA-256: `02d0ee33e96e4a1c3d2b69068edd5b01f0cc1e5a78049e033ba9af733a4f332f`
- Lines: 310
- Tests: 8
- KORPUS imports: `korpus.api.dependencies`, `korpus.application.answer_query`, `korpus.application.policy`, `korpus.application.retrieval`, `korpus.domain.models`

Test predicates:
- `test_a_better_matched_analytical_source_is_not_cited_beside_an_official_one`
- `test_a_lower_ranked_source_cannot_veto_the_answer`
- `test_approval_refuses_a_second_current_version_of_one_document`
- `test_one_version_is_selected_once_however_many_spans_match`
- `test_similarity_cannot_promote_a_weaker_source_above_a_stronger_one`
- `test_the_retriever_carries_the_same_cap_its_diversifier_defaults_to`
- `test_the_running_configuration_cites_one_span_per_version`
- `test_two_live_versions_of_one_document_require_a_human`

## `apps/api/tests/test_billing_events.py`

- SHA-256: `d4d7b114e65d97296e4fee2928b96c16f1c143fa67f0ad582cf252e1c1cba864`
- Lines: 584
- Tests: 18
- KORPUS imports: `korpus.application.tenancy_ports`, `korpus.domain.tenancy`, `korpus.infrastructure.deterministic_billing`, `korpus.infrastructure.tenancy_schema`

Test predicates:
- `test_a_canceled_subscription_cannot_be_reactivated`
- `test_a_genuinely_older_event_is_still_rejected`
- `test_a_legitimate_in_order_event_is_not_rejected_as_a_replay`
- `test_a_non_idempotency_integrity_error_is_not_swallowed_as_a_duplicate`
- `test_a_redelivered_event_changes_nothing`
- `test_a_replayed_older_event_does_not_move_the_subscription_backwards`
- `test_a_storage_failure_leaves_no_half_applied_event`
- `test_a_subscription_cannot_be_started_on_an_unknown_plan`
- `test_a_tampered_body_no_longer_matches_its_signature`
- `test_a_verified_event_activates_and_is_recorded`
- `test_an_event_for_an_account_that_does_not_exist_cannot_start_a_subscription`
- `test_an_event_naming_an_unknown_subscription_is_recorded_and_refused`
- `test_an_oversized_payload_is_refused_before_it_is_parsed`
- `test_an_unsigned_event_is_refused`
- `test_malformed_payloads_are_refused_and_change_nothing`
- `test_the_first_event_records_the_providers_own_subscription_id`
- `test_the_webhook_secret_must_be_long_enough_to_be_a_secret`
- `test_two_concurrent_deliveries_apply_once`

## `apps/api/tests/test_boundary_coverage_v5.py`

- SHA-256: `b6db4e6786338373c4a6f0f0bdf5fe27eb4958f7a520be1621ee8d244e250108`
- Lines: 503
- Tests: 7
- KORPUS imports: `korpus`, `korpus.domain.models`, `korpus.infrastructure`, `korpus.infrastructure.extraction`, `korpus.infrastructure.object_store`, `korpus.infrastructure.repository`, `korpus.infrastructure.semantic`

Test predicates:
- `test_cli_read_commands_close_all_resources`
- `test_cli_reconciliation_and_worker_boundaries`
- `test_embedding_provider_normalization_validation_health_and_close`
- `test_local_object_store_full_lifecycle_and_fail_closed_paths`
- `test_parser_worker_success_and_failure`
- `test_pgvector_search_upsert_governance_and_lifecycle`
- `test_s3_path_download_inventory_and_cleanup`

## `apps/api/tests/test_break_glass.py`

- SHA-256: `58859e365cd75d436cd76556c1159c0c8ad331aba62f87d8bf611b929785cd7d`
- Lines: 136
- Tests: 11
- KORPUS imports: `korpus.application.break_glass`, `korpus.domain.models`

Test predicates:
- `test_a_formality_is_not_a_reason`
- `test_a_grant_belongs_to_the_subject_it_was_issued_to`
- `test_a_grant_cannot_outlast_the_ceiling`
- `test_a_grant_expires`
- `test_a_grant_never_carries_approval_authority`
- `test_a_grant_that_widens_nothing_is_refused`
- `test_a_grant_widens_reach_and_records_both_names`
- `test_an_approver_cannot_grant_above_their_own_clearance`
- `test_one_person_cannot_break_glass_alone`
- `test_roles_are_not_widened_by_an_elevation`
- `test_someone_without_authority_cannot_approve`

## `apps/api/tests/test_browser_oidc.py`

- SHA-256: `551335de3e19d6900bead6d8f6f48718eef48102aa8f6d9d9fe5c163f43407f7`
- Lines: 229
- Tests: 4
- KORPUS imports: `korpus.config`, `korpus.main`, `korpus.security.browser_oidc`

Test predicates:
- `test_browser_oidc_callback_keeps_tokens_http_only_and_enforces_csrf`
- `test_browser_session_codec_rejects_tampering_and_expiry`
- `test_oidc_authorization_url_uses_state_nonce_and_s256_pkce`
- `test_the_codec_rejects_a_second_spelling_of_the_same_token`

## `apps/api/tests/test_browser_session_refusals.py`

- SHA-256: `1a3f74e3d962af5897991cd5dc8afd3845af2fb188f1da63067238d08d7feb26`
- Lines: 90
- Tests: 9
- KORPUS imports: `korpus.security.browser_oidc`

Test predicates:
- `test_a_malformed_envelope_is_refused`
- `test_a_sealed_session_opens_with_its_payload`
- `test_a_session_issued_in_the_future_is_refused`
- `test_a_short_secret_is_refused`
- `test_a_tampered_ciphertext_is_refused`
- `test_an_envelope_from_another_secret_is_refused`
- `test_an_envelope_sealed_for_another_purpose_does_not_open_as_a_session`
- `test_an_envelope_that_could_not_be_valid_is_refused_at_seal`
- `test_an_expired_session_is_refused`

## `apps/api/tests/test_build_provenance.py`

- SHA-256: `ca99955c6480e774d12f0d48c9cbaf32cc2d357952f6fb44239741981e7c8165`
- Lines: 121
- Tests: 4
- KORPUS imports: none

Test predicates:
- `test_an_intact_statement_verifies`
- `test_another_key_does_not_verify`
- `test_editing_a_material_digest_breaks_the_signature`
- `test_the_statement_says_the_builder_is_unattested`

## `apps/api/tests/test_calibration.py`

- SHA-256: `88d19790509dedb7b3a94e08c86498d8fd5a3b7cca4fd473fc4c79d67640d9f5`
- Lines: 122
- Tests: 5
- KORPUS imports: `korpus.application.calibration`, `korpus.config`

Test predicates:
- `test_calibration_profile_and_bound_artifacts_reject_tampering`
- `test_controlled_settings_accept_valid_profile`
- `test_controlled_settings_reject_unvalidated_calibration`
- `test_dataset_digest_is_content_addressed`
- `test_finite_sample_risk_bound_is_monotone_and_fail_closed`

## `apps/api/tests/test_ci_production_evidence_plumbing.py`

- SHA-256: `f948025dda7222f0b4cbaf60986f2272c878be542a9ead5d648d3d5670447011`
- Lines: 70
- Tests: 7
- KORPUS imports: none

Test predicates:
- `test_container_scan_marker_is_handed_to_supply_chain_gate`
- `test_evidence_registry_tracks_the_canonical_load_report_name`
- `test_package_consumes_postgres_artifacts_and_stages_external_evidence_before_gate`
- `test_package_materializes_all_externally_bound_required_gates`
- `test_postgres_job_materializes_network_load_evidence_as_fixture`
- `test_redteam_validator_uses_protected_runtime_trust_without_source_mutation`
- `test_supply_chain_attestation_is_optional_but_gate_remains_mandatory`

## `apps/api/tests/test_ci_security_summary.py`

- SHA-256: `b50018fc02a4b5bb3c44f0017c70abfde9c07d29279fe766c59a5ef3c7bd95eb`
- Lines: 42
- Tests: 2
- KORPUS imports: none

Test predicates:
- `test_exact_clean_scanner_set_passes`
- `test_missing_nonzero_or_stale_marker_fails`

## `apps/api/tests/test_citation_alignment.py`

- SHA-256: `276e8709c5683e2f796c9781eb60afde367a61d9b7508a7bc0cdebca92314e29`
- Lines: 145
- Tests: 8
- KORPUS imports: `korpus.api.dependencies`, `korpus.application.answer_query`, `korpus.application.evidence`, `korpus.application.policy`, `korpus.application.risk`, `korpus.config`, `korpus.domain.models`

Test predicates:
- `test_a_claim_referencing_an_uncarried_span_gets_no_credit`
- `test_a_claim_with_no_reference_at_all_is_unsupported`
- `test_a_misaligned_answer_stops_instead_of_raising`
- `test_every_claim_backed_by_a_carried_citation_is_full_coverage`
- `test_extra_citations_do_not_push_coverage_above_one`
- `test_no_claims_is_zero_coverage_not_a_division_error`
- `test_partially_valid_references_earn_nothing_for_that_claim`
- `test_the_aligned_path_reports_coverage_by_claim`

## `apps/api/tests/test_clean_source_release_boundary.py`

- SHA-256: `ffc54b94a97494fca3619da217a34f8f424665de1167ba4e8701e30c5e606dca`
- Lines: 27
- Tests: 2
- KORPUS imports: none

Test predicates:
- `test_package_only_metadata_cannot_expand_source_authority`
- `test_package_producer_excludes_git_history_by_construction`

## `apps/api/tests/test_configuration_typos.py`

- SHA-256: `58e0aad7b51b8c66eddd0c6cb4592afc5cf088c80cdaccda661fc3d8536feaa5`
- Lines: 120
- Tests: 9
- KORPUS imports: `korpus.application.deployment`, `korpus.config`, `korpus.main`

Test predicates:
- `test_a_misspelled_setting_is_named`
- `test_every_settings_field_is_reachable_by_its_prefixed_name`
- `test_mutation_job_control_is_a_declared_operational_variable`
- `test_no_deployed_environment_would_be_refused_by_the_check`
- `test_operational_variables_are_not_flagged`
- `test_the_app_refuses_to_start_on_an_unrecognised_variable`
- `test_the_app_starts_when_every_variable_is_recognised`
- `test_the_correctly_spelled_setting_is_accepted`
- `test_variables_outside_the_namespace_are_ignored`

## `apps/api/tests/test_contracts.py`

- SHA-256: `e96713b9e68e09dd5eebc8d255f42a2f0360789121c241a6ff9efa43dfdd10db`
- Lines: 33
- Tests: 2
- KORPUS imports: none

Test predicates:
- `test_contract_rejects_duplicate_or_invalid_corpus_ids`
- `test_openapi_contract_exposes_evidence_and_decision_provenance`

## `apps/api/tests/test_controlled_configuration_refusals.py`

- SHA-256: `a8d2c9be166d7c1c1cce28001f55b021bcbbb771a54b7033758d65f1f0d796e7`
- Lines: 234
- Tests: 4
- KORPUS imports: `korpus.config`

Test predicates:
- `test_a_controlled_deployment_refuses_each_weakening`
- `test_a_local_environment_is_not_held_to_the_controlled_requirements`
- `test_every_controlled_environment_name_carries_the_same_refusals`
- `test_the_base_controlled_configuration_is_accepted`

## `apps/api/tests/test_conversation_retention.py`

- SHA-256: `cfb9019580d4e40b19f6f0fed49ff6bb25f885555a8ff6506adc0fe9782b3a22`
- Lines: 247
- Tests: 13
- KORPUS imports: `korpus.application.conversation_retention`, `korpus.domain.tenancy`, `korpus.infrastructure.tenancy_schema`

Test predicates:
- `test_a_naive_timestamp_is_read_as_utc_rather_than_crashing`
- `test_age_is_measured_from_the_last_activity_not_from_creation`
- `test_an_impossible_window_is_refused_rather_than_clamped`
- `test_an_invalid_window_stops_the_job_rather_than_being_clamped`
- `test_deleting_nothing_is_not_an_error`
- `test_deleting_removes_the_named_conversations_and_nothing_else`
- `test_no_declared_window_is_reported_as_undecided_not_as_compliant`
- `test_the_activity_listing_spans_every_account`
- `test_the_boundary_keeps_rather_than_deletes`
- `test_the_report_names_what_it_would_delete`
- `test_the_script_deletes_only_with_a_window_and_an_explicit_apply`
- `test_the_script_refuses_to_apply_a_policy_nobody_declared`
- `test_the_script_reports_an_undeclared_policy_as_a_finding`

## `apps/api/tests/test_conversations.py`

- SHA-256: `cc0b2b54dffc3b368416ea9aa58cc899a30fbba45f8f1a082b7dac604cb225bd`
- Lines: 401
- Tests: 16
- KORPUS imports: `korpus.application.conversations`, `korpus.application.tenancy_ports`, `korpus.domain.tenancy`

Test predicates:
- `test_a_conversation_is_visible_only_to_its_owner`
- `test_a_conversation_will_not_grow_without_limit`
- `test_a_stored_answer_remembers_whether_it_was_one`
- `test_a_truncated_list_says_it_was_truncated`
- `test_a_truncated_transcript_says_its_newest_turns_are_missing`
- `test_a_turn_stored_before_the_verdict_existed_reports_it_as_unrecorded`
- `test_an_archived_conversation_takes_no_more_questions`
- `test_an_empty_or_oversized_question_is_refused`
- `test_an_exact_page_does_not_claim_there_is_more`
- `test_an_unknown_conversation_and_a_foreign_one_are_the_same_refusal`
- `test_another_account_cannot_append_to_or_archive_a_conversation`
- `test_another_accounts_messages_cannot_be_read`
- `test_purging_an_account_removes_its_history_and_nobody_elses`
- `test_the_conversation_service_offers_no_way_to_turn_history_into_evidence`
- `test_the_message_limit_is_checked_without_reading_the_whole_conversation`
- `test_what_the_system_said_is_stored_as_the_system_having_said_it`

## `apps/api/tests/test_corpus_backup_drill.py`

- SHA-256: `368c4d9a8f3638bf2af40911423cebf55414b2b645c81b91538d18c7fae8015b`
- Lines: 171
- Tests: 3
- KORPUS imports: none

Test predicates:
- `test_a_backup_restores_to_a_corpus_that_can_be_cited`
- `test_a_tampered_backup_is_refused_before_it_is_decrypted`
- `test_the_drill_refuses_a_corpus_that_restores_empty`

## `apps/api/tests/test_corpus_governance.py`

- SHA-256: `acfab19a0bc8e301780c5f6e361545bf82d248694592f0c326b490884b50f725`
- Lines: 91
- Tests: 3
- KORPUS imports: `korpus.domain.models`, `korpus.security.corpus_governance`

Test predicates:
- `test_corpus_governance_is_content_addressed_and_fail_closed`
- `test_ingestion_authority_classification_ocr_and_egress_are_governed`
- `test_legal_hold_cannot_enable_deletion`

## `apps/api/tests/test_corpus_release_identity.py`

- SHA-256: `fdc635dff12eea78c715f38ce9d55625e1bbe26253dde37f647bde6a2f1785fb`
- Lines: 164
- Tests: 5
- KORPUS imports: `korpus.domain.models`

Test predicates:
- `test_a_corpus_the_reader_cannot_reach_yields_the_empty_digest`
- `test_a_quarantined_version_is_not_in_the_release`
- `test_a_version_not_yet_in_force_is_not_in_the_release`
- `test_a_version_that_changes_changes_the_release_id`
- `test_the_release_id_equals_the_definition_it_replaced`

## `apps/api/tests/test_corpus_release_manifest.py`

- SHA-256: `73c49a4880015c0767ffa2f9961adb18baf33cc2194b2e965060adb7241a115c`
- Lines: 188
- Tests: 5
- KORPUS imports: none

Test predicates:
- `test_a_different_corpus_is_reported_as_a_different_release`
- `test_a_frozen_release_verifies_against_the_corpus_it_names`
- `test_a_manifest_signed_with_another_key_does_not_verify`
- `test_raising_an_authority_class_breaks_the_signature`
- `test_the_signer_is_recorded_as_an_assertion`

## `apps/api/tests/test_currency_lower_bound.py`

- SHA-256: `35c9dd7dace88ed96bb74f02e44af4bb24d406a9df051dca49ff90e5af7ee3bf`
- Lines: 153
- Tests: 5
- KORPUS imports: none

Test predicates:
- `test_a_version_with_no_lower_bound_at_all_cannot_be_approved`
- `test_an_approved_order_does_not_govern_before_it_took_effect`
- `test_publication_date_serves_as_the_lower_bound_when_effective_from_is_absent`
- `test_the_candidate_sql_excludes_an_unbounded_version`
- `test_the_projection_ignores_an_unbounded_version_already_in_the_database`

## `apps/api/tests/test_data_model_documents_every_table.py`

- SHA-256: `067e2fe60c85967e4024a18f4dc53813f0b8528ff3b068b1d5cc3061681d8182`
- Lines: 55
- Tests: 3
- KORPUS imports: `korpus.infrastructure.repository`

Test predicates:
- `test_every_table_the_system_creates_is_described`
- `test_nothing_is_described_that_does_not_exist`
- `test_the_appendix_is_read_from_the_appendix`

## `apps/api/tests/test_deployment_overlays.py`

- SHA-256: `45e5f2ebad2239779b1d61bf20ee63f0b71ec180ea5cce9a459e4fb61221aaab`
- Lines: 188
- Tests: 9
- KORPUS imports: `korpus.application.deployment`

Test predicates:
- `test_a_hostile_overlay_patch_is_caught`
- `test_a_patch_matching_nothing_is_refused`
- `test_an_unsupported_kustomization_field_is_refused`
- `test_every_shipped_variant_renders_and_satisfies_the_policy`
- `test_missing_workloads_are_reported`
- `test_strategic_merge_patches_are_applied`
- `test_the_overlay_actually_changes_the_rendered_output`
- `test_the_repository_ships_a_production_overlay_that_is_validated`
- `test_the_validator_script_reports_every_variant`

## `apps/api/tests/test_deployment_rendering_refusals.py`

- SHA-256: `86820a791d8bf7a7afa0c55b727e3ec240e75d0e5db9fff811990b8d18fe3e36`
- Lines: 267
- Tests: 13
- KORPUS imports: `korpus.application.deployment`

Test predicates:
- `test_a_base_renders_to_the_documents_it_lists`
- `test_a_container_that_loosens_its_own_context_is_reported`
- `test_a_directory_without_a_kustomization_is_refused`
- `test_a_field_the_renderer_does_not_understand_is_refused`
- `test_a_json6902_replace_reaches_the_rendered_document`
- `test_a_namespace_is_applied_to_every_document_except_namespaces`
- `test_a_patch_that_selects_nothing_is_refused`
- `test_a_patch_the_renderer_cannot_apply_is_refused`
- `test_a_pod_that_loosens_its_own_context_is_reported`
- `test_a_resource_that_does_not_exist_is_refused`
- `test_a_strategic_merge_patch_reaches_the_rendered_document`
- `test_an_empty_document_set_is_a_violation_not_a_clean_result`
- `test_discovery_finds_base_and_overlay_alike`

## `apps/api/tests/test_doctrine_catalog.py`

- SHA-256: `8b6c8328afd060ccc50e61e833e7a7291717827399c4b0a47dfc82df9d5d58af`
- Lines: 127
- Tests: 11
- KORPUS imports: none

Test predicates:
- `test_a_blocked_entry_must_say_why`
- `test_a_duplicate_id_is_refused`
- `test_an_ingestible_entry_must_have_a_source_uri`
- `test_an_unknown_authority_class_is_refused`
- `test_non_open_rights_may_not_be_ingestible`
- `test_restricted_material_may_not_be_ingestible`
- `test_secondary_analysis_must_be_analytical`
- `test_the_baseline_entry_is_actually_clean`
- `test_the_real_catalog_passes`
- `test_the_real_catalog_quarantines_the_restricted_nato_ew_doctrine`
- `test_unverified_provenance_must_require_a_second_source`

## `apps/api/tests/test_document_intake_refusals.py`

- SHA-256: `c65db388d182b6bdd5c26c04ba8529d23e4d411879ecf57e78ec835247028002`
- Lines: 181
- Tests: 21
- KORPUS imports: `korpus.infrastructure.extraction`

Test predicates:
- `test_a_json_document_is_normalised_rather_than_stored_verbatim`
- `test_a_malformed_pdf_is_refused`
- `test_a_missing_file_is_refused`
- `test_a_pdf_exceeding_the_page_limit_is_refused`
- `test_a_pdf_extension_over_non_pdf_bytes_is_refused`
- `test_a_pdf_extension_with_a_text_mime_type_is_refused`
- `test_a_pdf_mime_type_without_a_pdf_extension_is_refused`
- `test_a_pdf_with_no_embedded_text_and_ocr_disabled_is_refused`
- `test_a_plain_text_document_is_extracted`
- `test_a_utf8_bom_is_accepted_and_stripped`
- `test_a_whitespace_only_document_is_refused`
- `test_a_zero_byte_file_is_refused`
- `test_an_empty_upload_is_refused`
- `test_an_encrypted_pdf_is_refused_rather_than_partially_read`
- `test_an_unsupported_extension_is_refused`
- `test_an_unsupported_mime_type_is_refused`
- `test_html_entities_are_decoded_into_the_text_that_is_quoted`
- `test_invalid_json_is_refused`
- `test_non_utf8_bytes_are_refused`
- `test_octet_stream_is_tolerated_because_browsers_send_it`
- `test_script_and_style_content_never_becomes_indexable_text`

## `apps/api/tests/test_durable_ingestion_jobs.py`

- SHA-256: `24b7345ff5ef39685f34b58b6f44dd99dc6959d65e4a63110d59854af4559cde`
- Lines: 317
- Tests: 7
- KORPUS imports: `korpus.application.ingestion`, `korpus.application.ingestion_jobs`, `korpus.application.policy`, `korpus.composition`, `korpus.config`, `korpus.domain.models`, `korpus.infrastructure.ingestion_jobs`, `korpus.infrastructure.object_store`, `korpus.infrastructure.repository`, `korpus.main`, `korpus.security.auth`

Test predicates:
- `test_a_worker_cannot_complete_a_job_it_does_not_hold`
- `test_a_worker_cannot_mark_a_job_succeeded_that_it_does_not_hold`
- `test_durable_job_submission_is_non_parsing_and_worker_completes`
- `test_job_failure_is_dead_lettered_for_deterministic_parser_error`
- `test_job_lease_is_exclusive`
- `test_object_inventory_reconciliation_detects_missing_and_orphaned_files`
- `test_synchronous_endpoint_is_disabled_in_durable_mode`

## `apps/api/tests/test_egress_material_ceiling.py`

- SHA-256: `545debb16bb029f57644bd666c721988515f0c54198597bbb4a2590c92d07da4`
- Lines: 214
- Tests: 7
- KORPUS imports: `korpus.application.answer_query`, `korpus.application.egress`, `korpus.domain.models`

Test predicates:
- `test_a_claim_backed_by_an_unknown_span_is_treated_as_the_most_restrictive`
- `test_a_raised_ceiling_admits_material_up_to_it`
- `test_local_only_carries_restricted_material_because_it_never_leaves`
- `test_permits_material_ignores_the_ceiling_when_the_model_is_local`
- `test_permits_material_is_a_ceiling_not_a_floor`
- `test_public_material_does_reach_the_composer`
- `test_restricted_material_never_reaches_an_external_composer`

## `apps/api/tests/test_embedding_coverage.py`

- SHA-256: `38ac168856d5ce912c429da94e9ab06ae0366789d5e94737dbd6d0ace2cb7646`
- Lines: 113
- Tests: 9
- KORPUS imports: `korpus.application.embedding_coverage`

Test predicates:
- `test_a_fully_embedded_corpus_is_complete`
- `test_a_stale_vector_outranks_a_missing_one`
- `test_an_empty_corpus_covers_nothing_rather_than_everything`
- `test_missing_vectors_call_for_a_backfill`
- `test_required_semantic_mode_refuses_an_empty_index`
- `test_required_semantic_mode_refuses_an_incomplete_index`
- `test_required_semantic_mode_serves_a_complete_index`
- `test_the_report_names_the_model_it_measured_against`
- `test_vectors_under_a_superseded_model_call_for_a_migration`

## `apps/api/tests/test_embedding_migration.py`

- SHA-256: `0392a46e8fd849035ca62590f827b69d9c5f92fc044419cbb5334e764b989026`
- Lines: 173
- Tests: 16
- KORPUS imports: `korpus.application.embedding_migration`

Test predicates:
- `test_a_migration_is_planned_as_resumable_batches`
- `test_a_plan_that_cannot_be_executed_is_refused`
- `test_an_empty_corpus_produces_no_batches_but_is_not_an_error`
- `test_an_empty_index_is_not_complete_coverage`
- `test_migrating_a_model_to_itself_is_refused`
- `test_resume_returns_nothing_when_every_batch_is_done`
- `test_resume_returns_the_first_gap_not_the_next_index`
- `test_retiring_after_a_coverage_regression_is_refused`
- `test_retiring_before_the_switch_is_refused`
- `test_retiring_is_allowed_once_the_switch_holds`
- `test_rollback_is_checked_before_it_is_needed`
- `test_the_plan_says_what_executing_it_would_not_prove`
- `test_the_stages_never_retire_before_switching`
- `test_the_switch_is_allowed_at_complete_coverage`
- `test_the_switch_requires_complete_coverage`
- `test_the_switch_requires_no_stale_vectors`

## `apps/api/tests/test_entitlement_gate.py`

- SHA-256: `d39d553998b46bdf677b653d54c07ae25c947b75ae6700a797af2635a97c9ee3`
- Lines: 309
- Tests: 10
- KORPUS imports: `korpus.application.paid_access`, `korpus.application.policy`, `korpus.domain.tenancy`, `korpus.infrastructure.tenancy_schema`

Test predicates:
- `test_a_disabled_account_entitles_nothing_however_much_it_paid`
- `test_a_free_corpus_needs_no_subscription`
- `test_a_past_due_subscription_pays_for_nothing`
- `test_a_plan_cannot_grant_a_corpus_the_identity_does_not_hold`
- `test_a_subscription_whose_plan_vanished_entitles_nothing`
- `test_an_active_subscription_permits_only_what_it_pays_for`
- `test_an_expired_period_stops_paying_without_any_event_arriving`
- `test_the_schema_refuses_a_subscription_without_a_plan`
- `test_with_the_gate_off_the_answer_is_the_policy_engines_own`
- `test_without_an_active_subscription_the_paid_corpus_is_denied`

## `apps/api/tests/test_entitlement_projection_refusals.py`

- SHA-256: `cd813936c50c8464469d2f0ba4bb140a7ff1b2e0489b62b4af28c7fcc3e4e5f8`
- Lines: 159
- Tests: 11
- KORPUS imports: `korpus.security.entitlements`

Test predicates:
- `test_a_denied_subject_cannot_also_carry_an_explicit_grant`
- `test_a_profile_whose_bytes_changed_is_refused`
- `test_a_string_audience_claim_is_accepted_when_it_matches`
- `test_a_string_groups_claim_is_treated_as_one_group`
- `test_a_subject_that_maps_to_no_role_is_refused`
- `test_a_token_that_does_not_belong_here_is_refused`
- `test_a_valid_subject_is_projected_through_the_profile`
- `test_an_unknown_group_contributes_nothing_rather_than_failing_open`
- `test_group_and_subject_grants_combine_by_union_and_maximum`
- `test_malformed_scope_names_are_refused`
- `test_the_canonical_digest_ignores_key_order`

## `apps/api/tests/test_entitlement_revocation.py`

- SHA-256: `50ba451adff8aa9016f70f69e6c65caace1de461b624ade7ab0d1253cc6366d9`
- Lines: 123
- Tests: 5
- KORPUS imports: `korpus.config`, `korpus.security.auth`, `korpus.security.entitlements`

Test predicates:
- `test_a_pinned_digest_refuses_a_changed_profile_rather_than_serving_the_old_one`
- `test_a_rewrite_with_identical_content_is_not_a_reload`
- `test_revocation_on_disk_denies_the_subject_without_a_restart`
- `test_settings_still_accept_a_profile_path`
- `test_the_cached_loader_is_not_reachable_with_a_stale_key`

## `apps/api/tests/test_environment_drift.py`

- SHA-256: `c253afedece8d8044da02c4dc2959f645b21fa1fef96b45c6389352510f0f50a`
- Lines: 280
- Tests: 26
- KORPUS imports: `korpus.application`

Test predicates:
- `test_a_fresh_observation_is_admissible`
- `test_a_future_timestamp_is_refused`
- `test_a_malformed_timestamp_is_refused`
- `test_a_naive_timestamp_is_refused_rather_than_assumed_utc`
- `test_absent_from_observation_is_unobserved_not_in_sync`
- `test_an_observation_past_the_limit_is_refused`
- `test_an_observation_without_a_timestamp_is_refused`
- `test_blocked_reason_counts_every_state`
- `test_changed_digest_is_drift_and_carries_both_sides`
- `test_desired_state_is_read_from_the_manifest_not_the_working_tree`
- `test_empty_desired_state_with_running_artefacts_is_not_in_sync`
- `test_findings_are_ordered_so_two_runs_compare`
- `test_manifest_without_records_refuses_rather_than_returning_empty`
- `test_matching_digests_are_in_sync`
- `test_observing_an_empty_tree_reports_every_artefact_missing`
- `test_present_but_unreadable_is_unobserved_not_drift`
- `test_report_serialises_with_counts_per_state`
- `test_script_exits_nonzero_when_a_declared_artefact_changed`
- `test_script_observes_the_working_tree_and_matches_the_manifest`
- `test_script_refuses_to_answer_without_an_observation`
- `test_script_reports_a_deleted_artefact_as_unobserved`
- `test_the_boundary_second_is_still_admissible`
- `test_the_script_creates_the_directory_it_was_told_to_write_into`
- `test_the_script_refuses_a_stale_observation_instead_of_comparing_it`
- `test_the_script_stamps_the_observation_where_it_is_taken`
- `test_undeclared_artefact_is_extra_not_drift`

## `apps/api/tests/test_evidence_provenance.py`

- SHA-256: `3e5bb75fd4a7620f49565b651f29ef09343fe403a84b9b080fe757482728b2b8`
- Lines: 212
- Tests: 14
- KORPUS imports: `korpus.application.operations`, `korpus.application.provenance`

Test predicates:
- `test_digest_changes_when_evidence_bearing_source_changes`
- `test_digest_ignores_documentation_so_the_gate_stays_signal`
- `test_digest_ignores_generated_bytecode_and_caches`
- `test_digest_separates_path_from_content`
- `test_gate_passes_only_when_every_report_carries_this_tree`
- `test_gate_rejects_a_single_stale_report_among_fresh_ones`
- `test_gate_rejects_evidence_from_a_foreign_tree`
- `test_gate_rejects_reports_without_provenance`
- `test_gate_script_exits_nonzero_on_foreign_evidence`
- `test_gate_without_a_digest_cannot_pass`
- `test_malformed_provenance_is_not_provenance`
- `test_stamp_binds_to_the_tree_it_is_given`
- `test_stamp_requires_a_generator`
- `test_verify_reports_rejects_a_malformed_expected_digest`

## `apps/api/tests/test_evidence_registry.py`

- SHA-256: `9787dcfd1c9c94716881747cedea38f4f6ad4df26af53c2148684cc672cf9b27`
- Lines: 176
- Tests: 13
- KORPUS imports: `korpus.application.evidence_registry`

Test predicates:
- `test_a_ci_job_citation_resolves_against_the_pipeline`
- `test_a_deleted_test_inside_an_existing_file_is_reported`
- `test_a_directory_citation_is_accepted`
- `test_a_missing_file_is_reported`
- `test_a_mitigated_finding_may_rest_on_documents`
- `test_a_present_test_resolves`
- `test_a_produced_artifact_is_still_checked_when_the_caller_runs_after_its_producer`
- `test_a_selector_on_a_non_test_file_is_refused`
- `test_closure_claimed_on_prose_alone_is_rejected`
- `test_only_a_test_or_a_ci_job_counts_as_executable`
- `test_parametrized_citations_resolve_to_their_base_name`
- `test_the_relaxation_cannot_excuse_a_missing_test`
- `test_the_shipped_registry_cites_only_evidence_that_exists`

## `apps/api/tests/test_exact_environment_evidence.py`

- SHA-256: `612eb1f3f19f5f1bc21661f9eb77ba20db29a97f6fa4ac9011c2b215c938168a`
- Lines: 40
- Tests: 4
- KORPUS imports: `korpus.application.exact_environment`

Test predicates:
- `test_exact_environment_accepts_only_exact_lock_python_and_allowlist`
- `test_missing_or_version_drift_remains_fail_closed`
- `test_unmanaged_distribution_prevents_exact_environment_claim`
- `test_wrong_python_patch_version_prevents_exact_environment_claim`

## `apps/api/tests/test_exception_handling_discipline.py`

- SHA-256: `9acb514592b503cb67f50eae4da95c4e4c9a16a8634eee31c63f2882dce267b5`
- Lines: 138
- Tests: 4
- KORPUS imports: none

Test predicates:
- `test_no_bare_except_hides_which_failure_occurred`
- `test_no_broad_handler_is_an_empty_body`
- `test_no_broad_handler_turns_a_fault_into_evidence_of_health`
- `test_there_are_broad_handlers_to_judge`

## `apps/api/tests/test_external_production_evidence_staging.py`

- SHA-256: `9c2526716d7b9c04c232f5f57665fbfd82b2e97f15f804a84994958f80c7b30d`
- Lines: 40
- Tests: 3
- KORPUS imports: none

Test predicates:
- `test_complete_group_is_staged_but_not_declared_valid`
- `test_no_external_evidence_is_a_noop`
- `test_partial_group_fails_closed`

## `apps/api/tests/test_external_redteam_admissibility.py`

- SHA-256: `4cfa3ad4fcc4e072b2b84428dee0c54e86d050ba81ab4bcb9ca443aa0e45872b`
- Lines: 98
- Tests: 9
- KORPUS imports: `korpus.application.external_redteam`, `korpus.application.provenance`, `korpus.release`

Test predicates:
- `test_all_required_families_and_no_blocking_findings_pass_content_recomputation`
- `test_blocking_finding_must_be_verified_fixed_not_merely_risk_accepted`
- `test_declared_pass_cannot_hide_missing_attack_family`
- `test_open_blocking_finding_refuses_promotion`
- `test_signed_internal_report_cannot_claim_external_independence`
- `test_trusted_complete_structured_report_passes_external_gate`
- `test_trusted_signature_cannot_bypass_wrong_preregistration`
- `test_trusted_signature_cannot_turn_structurally_incomplete_report_into_pass`
- `test_valid_signature_without_preadmitted_trust_root_is_rejected`

## `apps/api/tests/test_extraction.py`

- SHA-256: `54fbb10e59e0b2e202b5254446151880ce3655837d6eda5c3a42d0d2cf26f9b5`
- Lines: 200
- Tests: 10
- KORPUS imports: `korpus.application.extraction_quality`, `korpus.infrastructure.extraction`

Test predicates:
- `test_a_docx_declaring_an_entity_is_refused`
- `test_a_docx_without_a_body_is_refused`
- `test_a_docx_yields_its_paragraphs_in_order`
- `test_a_zip_renamed_to_docx_is_refused_before_the_parser`
- `test_chunking_invariants_hold_over_seeded_random_corpus`
- `test_chunking_rejects_invalid_geometry_and_span_explosion`
- `test_empty_malformed_and_type_confused_documents_fail_closed`
- `test_html_active_content_is_removed`
- `test_normalisation_keeps_the_column_gap_a_flattened_table_leaves`
- `test_plain_text_extraction_and_chunking`

## `apps/api/tests/test_extraction_quality_governance.py`

- SHA-256: `5479046a023343690696bf07c01747aa47979c99b8c4a32cf4da163f1321ad31`
- Lines: 38
- Tests: 1
- KORPUS imports: none

Test predicates:
- `test_low_quality_extraction_requires_explicit_reviewer_acknowledgement`

## `apps/api/tests/test_foreign_supersession.py`

- SHA-256: `c427e258e4eb7e7f496c8ca7a78d7b537b0fd6b33130d78b62c9e1fec3cb74d8`
- Lines: 142
- Tests: 3
- KORPUS imports: `korpus.domain.models`

Test predicates:
- `test_a_crossing_edge_already_in_the_database_is_not_honoured`
- `test_a_new_document_cannot_declare_itself_successor_of_another`
- `test_the_victim_stays_answerable_after_the_attempt`

## `apps/api/tests/test_gate_negative_controls.py`

- SHA-256: `36d93c0e21ce0acc91fe5a91aeda1742d0169d5ad6992b08d666c6512e6e307e`
- Lines: 281
- Tests: 6
- KORPUS imports: `korpus.application.assurance`, `korpus.application.gate_inventory`, `korpus.application.provenance`

Test predicates:
- `test_every_assurance_predicate_has_a_negative_control`
- `test_every_gate_predicate_has_a_negative_control`
- `test_the_assurance_aggregator_can_fail_on_each_predicate`
- `test_the_operational_gate_can_fail_on_each_predicate`
- `test_the_passing_artifacts_actually_pass`
- `test_the_passing_assurance_inputs_actually_pass`

## `apps/api/tests/test_gate_parity.py`

- SHA-256: `9c76131f5d093c7dbb6ce3013abc98d2917fa2e61accee6743a04f1490ac999d`
- Lines: 1492
- Tests: 50
- KORPUS imports: none

Test predicates:
- `test_a_failed_generator_does_not_leave_its_previous_report_behind`
- `test_audit_closure_csv_generator_uses_canonical_lf_lines`
- `test_both_entry_points_run_the_same_quality_gate`
- `test_ci_does_not_retry_failing_jobs`
- `test_ci_pythonpath_contains_repository_root_for_scripts_package_imports`
- `test_every_ci_image_pins_an_exact_tag`
- `test_every_ci_job_that_runs_korpus_code_installs_the_locked_environment`
- `test_every_document_lookup_is_followed_by_an_access_decision`
- `test_every_install_of_a_lock_file_requires_those_hashes`
- `test_every_job_running_the_suite_uses_the_production_interpreter`
- `test_every_job_that_runs_the_suite_has_git_in_its_image`
- `test_every_lock_file_is_audited_for_known_vulnerabilities`
- `test_every_module_is_in_the_budget`
- `test_every_mutant_cites_a_test_that_exists`
- `test_every_pinned_dependency_carries_a_hash`
- `test_every_script_is_reachable_from_a_runner`
- `test_every_writing_console_previews_before_it_acts`
- `test_local_check_resolves_closure_evidence_only_after_producing_it`
- `test_mutant_ids_are_unique`
- `test_mutation_harness_does_not_credit_bootstrap_errors_as_kills`
- `test_mypy_is_invoked_so_that_its_configuration_applies`
- `test_no_job_reaches_a_relaxed_runner`
- `test_no_lock_file_pins_a_package_with_a_known_advisory_recorded_here`
- `test_no_migration_revision_exceeds_the_alembic_version_column`
- `test_no_mutant_covers_two_call_sites_at_once`
- `test_production_gate_generators_are_wired_to_the_ci_evidence_locations`
- `test_production_snapshot_wrapper_is_never_used_by_the_promotion_target`
- `test_real_browser_e2e_runner_cannot_disappear_silently`
- `test_ruff_configuration_is_resolved_from_the_repository_root`
- `test_runtime_lock_satisfies_every_declared_runtime_dependency`
- `test_scripts_reading_installed_metadata_run_under_the_locked_interpreter`
- `test_the_assurance_runner_resolves_closure_evidence_only_after_producing_it`
- `test_the_bootstrap_produces_a_corpus_that_can_actually_answer`
- `test_the_browsers_copy_of_the_request_contract_cannot_go_stale`
- `test_the_ci_configuration_is_parseable_yaml`
- `test_the_closure_builder_still_resolves_produced_artefacts`
- `test_the_closure_check_runs_after_whatever_produces_the_evidence_it_resolves`
- `test_the_coverage_thresholds_are_checked_where_coverage_is_produced`
- `test_the_coverage_thresholds_are_not_a_second_copy_of_the_policy`
- `test_the_desired_state_manifest_matches_the_files_it_fingerprints`
- `test_the_development_proxy_mirrors_the_production_edge`
- `test_the_drive_snapshot_is_a_snapshot_and_not_a_sync`
- `test_the_environment_drift_check_runs_in_the_pipeline`
- `test_the_import_pipeline_refuses_a_draft_manifest`
- `test_the_module_budget_is_enforced_in_both_entry_points`
- `test_the_pipeline_graph_is_consistent`
- `test_the_quality_gate_lints_every_directory_that_holds_korpus_code`
- `test_the_repository_walk_skips_everything_gitignore_excludes`
- `test_the_requirements_register_is_current`
- `test_the_web_gate_runs_its_own_negative_controls`

## `apps/api/tests/test_github_actions_policy.py`

- SHA-256: `cb0a65f6b48a60588d9aa3878fab473fe7b68a8e1464fb3f9ca99d92b2aff3c8`
- Lines: 72
- Tests: 6
- KORPUS imports: none

Test predicates:
- `test_checkout_credentials_must_not_persist`
- `test_mutable_runner_label_is_rejected`
- `test_privileged_pr_trigger_is_rejected`
- `test_release_workflow_rebuilds_bound_evidence_before_packaging`
- `test_repository_github_workflows_satisfy_policy`
- `test_unpinned_action_is_rejected`

## `apps/api/tests/test_governance_boundaries.py`

- SHA-256: `b77233da544f3681363924dc6d208e8fc4b298529be4b76a6f99bced3220e4d7`
- Lines: 206
- Tests: 10
- KORPUS imports: `korpus.domain.models`

Test predicates:
- `test_a_tier_may_only_be_set_on_approval`
- `test_an_adversary_source_cannot_be_approved`
- `test_an_adversary_source_never_reaches_an_answer`
- `test_an_approver_cannot_assign_a_tier_above_their_own_clearance`
- `test_an_unheld_corpus_denies_the_request_and_names_which`
- `test_approved_documents_still_answer_after_the_governance_changes`
- `test_only_normative_classes_may_govern_an_answer`
- `test_the_approver_sets_the_access_tier`
- `test_the_same_bytes_under_a_new_revision_are_a_new_version`
- `test_the_same_bytes_under_the_same_revision_are_still_a_duplicate`

## `apps/api/tests/test_handoff_contract.py`

- SHA-256: `892eaaae99aa8ae5f9e2466ff89b8893b7a5f3d8024b6e9863fc487f0bae5220`
- Lines: 69
- Tests: 3
- KORPUS imports: none

Test predicates:
- `test_local_handoff_contract_is_consistent_with_code_and_evidence`
- `test_partial_release_evidence_is_refused`
- `test_the_iteration_register_cannot_claim_completion_inside_this_repository`

## `apps/api/tests/test_health.py`

- SHA-256: `a75408451b3c6f382b916999456356d7201c42fc68e3388531f5c500107f50ba`
- Lines: 14
- Tests: 1
- KORPUS imports: none

Test predicates:
- `test_health_and_readiness_are_operational_not_information_side_channels`

## `apps/api/tests/test_http_audit_anchor.py`

- SHA-256: `f0b517435f1f9b61997edee1d0a8546953263ae54e2bb2f533e9627fec773008`
- Lines: 103
- Tests: 5
- KORPUS imports: `korpus.infrastructure.audit_anchor`

Test predicates:
- `test_remote_anchor_detects_payload_tampering`
- `test_remote_anchor_fails_closed_on_outage_and_forbids_reset`
- `test_remote_anchor_is_monotonic_idempotent_and_authenticated`
- `test_remote_anchor_rejects_conflicting_same_sequence`
- `test_remote_anchor_requires_https_except_loopback`

## `apps/api/tests/test_image_pinning.py`

- SHA-256: `f826f988f17f285c32757d14805794dd162d8a2035321dab4deac44eb39dfa72`
- Lines: 94
- Tests: 5
- KORPUS imports: `korpus.application.requirements`, `korpus.infrastructure_requirements`

Test predicates:
- `test_a_digest_pinned_image_is_accepted`
- `test_a_malformed_digest_is_not_a_digest`
- `test_a_tag_without_a_digest_is_refused`
- `test_every_compose_service_is_digest_pinned_today`
- `test_the_tag_survives_beside_the_digest`

## `apps/api/tests/test_import_graph.py`

- SHA-256: `9a6f71b3d36b4d10170dde4f2f4eb53f4b0a02f4a826f0464a8fe92168edffff`
- Lines: 25
- Tests: 2
- KORPUS imports: none

Test predicates:
- `test_cycle_detector_negative_control`
- `test_internal_import_graph_is_acyclic`

## `apps/api/tests/test_inference_security_gate.py`

- SHA-256: `7bca0cc6b4d2bbd945a205de0bb9eac89cafdd43f4074dcf82d1a8259dcdba4a`
- Lines: 57
- Tests: 4
- KORPUS imports: none

Test predicates:
- `test_inference_security_profile_is_fail_closed_on_empty_or_duplicate_scope`
- `test_inference_security_profile_rejects_missing_test_target`
- `test_production_assurance_has_a_tracked_inference_security_generator`
- `test_repository_inference_security_profile_has_executable_scope`

## `apps/api/tests/test_inference_status.py`

- SHA-256: `7e3a59937f72a9ba519a514f835f2518dd0f6449e642260c48414bb5956ddb41`
- Lines: 15
- Tests: 1
- KORPUS imports: none

Test predicates:
- `test_inference_status_is_fail_closed_by_default`

## `apps/api/tests/test_infrastructure_hardening.py`

- SHA-256: `cbfa024187062d637aaacecc22438f8f467bbb017ad7f95674f13f480cb3cc57`
- Lines: 449
- Tests: 15
- KORPUS imports: `korpus.config`, `korpus.domain.models`, `korpus.infrastructure.observability`, `korpus.main`, `korpus.security.auth`

Test predicates:
- `test_backup_crypto_roundtrip_and_tamper_detection`
- `test_backup_restore_scripts_are_cwd_independent_and_key_bound`
- `test_controlled_database_requires_server_identity_verification`
- `test_controlled_environment_rejects_sqlite_and_missing_anchor_auth`
- `test_malformed_host_header_is_rejected_before_routing`
- `test_metrics_token_is_fail_closed`
- `test_migration_mode_refuses_unversioned_schema`
- `test_not_ready_hides_the_internal_snapshot_without_the_metrics_token`
- `test_readiness_fails_when_anchor_backlog_exceeds_budget`
- `test_readiness_rejects_anchor_reset_without_replayable_outbox`
- `test_readiness_rejects_validly_signed_anchor_on_wrong_history`
- `test_reconcile_failures_are_observable`
- `test_semantic_configuration_cannot_drift_from_calibration`
- `test_static_infrastructure_contract_passes`
- `test_unknown_environment_cannot_bypass_controlled_profile`

## `apps/api/tests/test_ingestion.py`

- SHA-256: `fb158152d6b7ce57a89d36dbef5566787d451a19e292e6d400fda558c2e2c123`
- Lines: 114
- Tests: 6
- KORPUS imports: none

Test predicates:
- `test_classification_cannot_be_weaker_than_access_tier`
- `test_database_bundle_and_audit_roll_back_together`
- `test_duplicate_content_is_deduplicated_only_inside_same_corpus`
- `test_ingest_is_quarantined_then_approved_with_provenance`
- `test_unknown_authority_cannot_be_approved`
- `test_upload_size_limit_is_enforced_before_extraction`

## `apps/api/tests/test_intra_span_contradiction.py`

- SHA-256: `fa7a2eb3d39ce29ac168e0c439127089646d51d0b79bc1b32828f0dfbf73475f`
- Lines: 195
- Tests: 5
- KORPUS imports: `korpus.application.answer_query`, `korpus.domain.models`

Test predicates:
- `test_a_numeric_reversal_inside_one_span_stops_the_answer`
- `test_a_span_that_reverses_itself_stops_the_answer`
- `test_an_unrelated_eligible_span_does_not_veto_the_answer`
- `test_an_unrelated_neighbouring_sentence_does_not_block_the_answer`
- `test_the_scan_covers_eligible_spans_not_only_cited_ones`

## `apps/api/tests/test_leakage_measurement.py`

- SHA-256: `ffcd07dd891d2f87adec551f5c72515bf8fcc88faf6801906ed515da29fbcdd3`
- Lines: 60
- Tests: 4
- KORPUS imports: none

Test predicates:
- `test_a_report_without_the_field_at_all_fails_the_gate`
- `test_the_gate_fails_on_the_historical_denominator`
- `test_the_gate_fails_when_the_metric_had_nothing_to_measure`
- `test_the_gate_passes_when_leakage_was_measured_and_none_occurred`

## `apps/api/tests/test_liqpay_billing.py`

- SHA-256: `b081bf70d559b879c77e9eb6d3409056976912adb659b54ea9b0a88986b2cdb1`
- Lines: 415
- Tests: 11
- KORPUS imports: `korpus.application.checkout`, `korpus.application.subscriptions`, `korpus.application.tenancy_ports`, `korpus.config`, `korpus.domain.models`, `korpus.domain.tenancy`, `korpus.infrastructure.liqpay`, `korpus.main`, `korpus.security.auth`

Test predicates:
- `test_checkout_uses_only_server_plan_values`
- `test_configured_plan_refuses_incomplete_commercial_terms`
- `test_deployment_plan_bootstrap_is_idempotent`
- `test_final_callback_activates_once_and_bounds_the_period`
- `test_http_callback_rejects_signed_wrong_amount`
- `test_http_checkout_and_callback_are_one_fail_closed_flow`
- `test_non_final_callback_is_acknowledge_only`
- `test_plan_price_and_currency_are_one_domain_value`
- `test_signed_amount_tampering_cannot_activate_access`
- `test_wrong_signature_and_other_merchant_are_rejected`
- `test_yearly_checkout_declares_yearly_recurrence`

## `apps/api/tests/test_load_probe_contract.py`

- SHA-256: `ca0b7488054bb204d7acff33474b75a411e6f06aaff7ce9737e47b6a08133ce8`
- Lines: 62
- Tests: 3
- KORPUS imports: none

Test predicates:
- `test_http_error_body_preserves_the_server_admission_reason`
- `test_malformed_error_body_is_not_silently_classified`
- `test_outcome_keeps_typed_refusal_reasons_separate_from_http_status`

## `apps/api/tests/test_malformed_pdf_containment.py`

- SHA-256: `98021cf9acc968902062e472177649fd9b11a1fc90df9d226bafbd75914dd1b1`
- Lines: 120
- Tests: 3
- KORPUS imports: `korpus.infrastructure`

Test predicates:
- `test_a_page_tree_that_fails_when_walked_leaves_as_a_named_refusal`
- `test_a_readable_page_tree_is_not_refused`
- `test_the_construction_guard_is_not_what_catches_it`

## `apps/api/tests/test_manifest_generation.py`

- SHA-256: `e6ceed9e9388e5808d85712da9f92fc0d5bb7389fe1a77cd16819f5a3fdc32ac`
- Lines: 108
- Tests: 6
- KORPUS imports: none

Test predicates:
- `test_distribution_manifest_includes_untracked_package_artifacts`
- `test_git_bundle_is_distribution_artifact_not_source`
- `test_manifest_binds_posix_mode`
- `test_manifest_root_changes_when_only_mode_changes`
- `test_manifest_uses_archive_files_without_git`
- `test_manifest_uses_only_git_tracked_files_in_worktree`

## `apps/api/tests/test_model_egress.py`

- SHA-256: `61e2224eafda42784d37c3662c2e35b4de8a8003f3da30e8f52f369dda9cb4e7`
- Lines: 187
- Tests: 13
- KORPUS imports: `korpus.application.egress`, `korpus.application.query_plan`, `korpus.config`, `korpus.infrastructure`, `korpus.infrastructure.anthropic_planner`, `korpus.tenancy_composition`

Test predicates:
- `test_a_disabled_posture_stops_the_composer_before_it_calls_out`
- `test_a_disabled_posture_stops_the_planner_before_it_calls_out`
- `test_a_non_http_scheme_is_refused`
- `test_local_only_permits_a_loopback_endpoint`
- `test_local_only_permits_private_ip_literals`
- `test_local_only_refuses_a_vendor_endpoint`
- `test_local_only_refuses_an_unconfigured_endpoint`
- `test_local_only_refuses_arbitrary_dns_names_even_if_the_first_lookup_would_be_private`
- `test_local_only_refuses_public_and_link_local_ip_literals`
- `test_local_only_refuses_the_cloud_metadata_endpoint`
- `test_model_disabled_refuses_even_a_local_endpoint`
- `test_the_permissive_posture_is_the_shipped_default`
- `test_the_settings_value_maps_onto_the_posture`

## `apps/api/tests/test_more_edges.py`

- SHA-256: `c3e763ae494216d54cdb23e38688f8239fe2834788e3658f97d1da747b034517`
- Lines: 64
- Tests: 2
- KORPUS imports: `korpus.application.policy`, `korpus.domain.models`, `korpus.infrastructure.object_store`

Test predicates:
- `test_access_tier_parse_and_document_decision`
- `test_object_store_is_content_addressed_atomic_and_filename_independent`

## `apps/api/tests/test_near_duplicate_governance.py`

- SHA-256: `85913801e30cc7f788bde7b08c2deaa24e40d5212b04027e82513604d94109a3`
- Lines: 43
- Tests: 1
- KORPUS imports: none

Test predicates:
- `test_near_duplicate_requires_explicit_metadata_acknowledgement`

## `apps/api/tests/test_noninterference_measurement.py`

- SHA-256: `3cd46d76826a6badc1280681af463f27c103de242b51b96da0eb0835095dc0d7`
- Lines: 115
- Tests: 5
- KORPUS imports: `korpus.application.noninterference`, `korpus.domain.models`

Test predicates:
- `test_a_clean_answer_reports_no_reasons`
- `test_an_answer_naming_a_withheld_identifier_is_recognised_as_a_leak`
- `test_an_answer_quoting_withheld_text_is_recognised_as_a_leak`
- `test_the_withheld_set_is_empty_for_the_reference_subject`
- `test_the_withheld_set_is_not_empty_for_a_subject_who_cannot_see_everything`

## `apps/api/tests/test_numeric_integrity.py`

- SHA-256: `0a92dd3e86267766b7f212fd32a04120b95bbc25f4a27613c96e0b6b0a45640d`
- Lines: 159
- Tests: 16
- KORPUS imports: `korpus.application.extraction_quality`, `korpus.application.numeric_integrity`

Test predicates:
- `test_a_decimal_range_is_compared_numerically_not_lexically`
- `test_a_letter_standing_in_for_a_digit_is_flagged`
- `test_a_number_split_by_a_space_is_flagged`
- `test_a_thousands_separator_is_not_a_split_number`
- `test_a_unit_on_the_same_line_is_not_flagged`
- `test_a_unit_separated_from_its_quantity_by_a_line_break_is_flagged`
- `test_an_inverted_range_is_flagged`
- `test_an_ordinary_passage_carries_no_suspicion`
- `test_an_ordinary_range_is_not_flagged`
- `test_numeric_damage_reaches_the_reviewer_through_the_extraction_quality_gate`
- `test_one_consistent_decimal_separator_is_not_flagged`
- `test_ordinary_cyrillic_text_beside_numbers_is_not_flagged`
- `test_samples_are_bounded_so_a_report_does_not_carry_the_passage`
- `test_text_without_quantities_is_not_suspicious`
- `test_the_combined_flag_set_stays_within_the_column_bound`
- `test_two_decimal_separators_in_one_passage_are_flagged`

## `apps/api/tests/test_object_store_integrity.py`

- SHA-256: `30753e593cc7084dc858950e3eea0427fd86249a070bae06a38ca63b44eab9ca`
- Lines: 186
- Tests: 17
- KORPUS imports: `korpus.infrastructure.object_store`

Test predicates:
- `test_a_failed_stream_leaves_no_partial_file_behind`
- `test_a_key_that_is_not_a_content_address_is_refused`
- `test_a_malformed_source_hash_is_refused`
- `test_a_valid_stream_writes_the_verified_bytes`
- `test_an_altered_object_is_refused_when_streamed_to_a_path`
- `test_an_object_altered_on_disk_is_refused_on_read`
- `test_an_object_larger_than_the_limit_is_refused_on_read`
- `test_an_object_larger_than_the_limit_is_refused_on_write`
- `test_an_object_round_trips_under_its_content_address`
- `test_content_that_does_not_match_its_declared_hash_is_refused`
- `test_healthcheck_reports_a_writable_store`
- `test_listing_reports_content_addresses_and_ignores_working_files`
- `test_put_path_refuses_a_file_whose_bytes_are_not_the_declared_hash`
- `test_put_path_stores_and_verifies_a_file`
- `test_storing_the_same_object_twice_is_idempotent`
- `test_the_store_refuses_to_be_created_with_a_nonsensical_limit`
- `test_the_store_root_is_not_world_readable`

## `apps/api/tests/test_observability.py`

- SHA-256: `68ab805644daa5534c3edefcac9c5610568e35e1be951fe04b19740c7eade9f3`
- Lines: 38
- Tests: 4
- KORPUS imports: `korpus.infrastructure.observability`

Test predicates:
- `test_admission_gauge_returns_to_zero_after_answer`
- `test_metrics_are_low_cardinality_and_exported`
- `test_metrics_endpoint_is_available`
- `test_security_metrics_reject_unbounded_or_invented_labels`

## `apps/api/tests/test_oidc.py`

- SHA-256: `5518177999fa422e3dc915e869031ec68dc45e89fa6fbdfef4b2c7a7b46ae379`
- Lines: 85
- Tests: 3
- KORPUS imports: `korpus.security.oidc`

Test predicates:
- `test_oidc_rejects_symmetric_or_insecure_configuration`
- `test_oidc_rejects_symmetric_unknown_and_duplicate_algorithms`
- `test_oidc_verifier_pins_algorithm_issuer_audience_and_kid`

## `apps/api/tests/test_oidc_assurance_refusals.py`

- SHA-256: `5a4f2d9d4fea479c616bbe930649738fc89ae9afaaa6bb22daeb90a6b2ad279f`
- Lines: 138
- Tests: 10
- KORPUS imports: `korpus.security.oidc`

Test predicates:
- `test_a_missing_acr_is_refused_when_one_is_required`
- `test_a_recent_multifactor_authentication_satisfies_the_policy`
- `test_a_single_factor_authentication_is_refused_when_mfa_is_required`
- `test_a_usable_verifier_is_accepted`
- `test_a_verifier_that_could_not_verify_anything_is_refused_at_construction`
- `test_an_authentication_from_the_future_is_refused`
- `test_an_authentication_older_than_policy_is_refused`
- `test_an_empty_amr_is_refused_rather_than_ignored`
- `test_an_unreadable_auth_time_is_refused`
- `test_any_recognised_second_factor_satisfies_the_requirement`

## `apps/api/tests/test_openai_model_adapter.py`

- SHA-256: `287bc904229af43992d653db317b49f6f7e177a93ec39b64f2722f437f09ed0b`
- Lines: 158
- Tests: 8
- KORPUS imports: `korpus.api.dependencies`, `korpus.application.egress`, `korpus.application.query_plan`, `korpus.config`, `korpus.infrastructure.openai_planner`, `korpus.model_settings`

Test predicates:
- `test_composition_root_selects_openai_without_leaking_provider_into_application`
- `test_model_api_key_can_come_from_a_secret_file`
- `test_model_disabled_refuses_before_openai_transport`
- `test_new_deployment_defaults_to_openai_sol_but_keeps_model_calls_disabled`
- `test_openai_composer_uses_same_contract_and_store_false`
- `test_openai_malformed_output_contributes_nothing`
- `test_openai_planner_uses_responses_api_store_false_and_bearer_auth`
- `test_openai_provider_requires_explicit_model_name`

## `apps/api/tests/test_operational_policies.py`

- SHA-256: `eff7fe2bed1bfcbdb06dc846c4e37ae83141f4c00f1456d123507348f757bbc8`
- Lines: 180
- Tests: 6
- KORPUS imports: none

Test predicates:
- `test_a_missing_backup_is_reported_as_missing`
- `test_a_policy_run_where_nothing_was_scanned_is_not_a_pass`
- `test_a_scanner_that_never_started_fails_the_policy`
- `test_a_stale_scan_fails`
- `test_an_external_clause_is_not_counted_as_a_failure`
- `test_without_a_kev_catalogue_findings_are_unknown_not_clean`

## `apps/api/tests/test_operations.py`

- SHA-256: `e02684a5c41686a1730fdb6fd1e2eea4b93a51b0e7642b989afbd90a11b8a631`
- Lines: 117
- Tests: 5
- KORPUS imports: `korpus.application.operations`, `korpus.application.provenance`

Test predicates:
- `test_js_divergence_is_bounded_symmetric_and_identity_zero`
- `test_js_divergence_rejects_undefined_inputs`
- `test_operational_gate_fails_closed_on_trust_regression`
- `test_operational_gate_passes_encoded_engineering_predicates_only`
- `test_operational_policy_is_valid_json_and_explicitly_not_authorization`

## `apps/api/tests/test_overload_http.py`

- SHA-256: `474d58edd134d2a741ef6b1ed8f15a84c41f80c4c91fd6883ba2554ee0ca3669`
- Lines: 18
- Tests: 2
- KORPUS imports: `korpus.api.overload_http`, `korpus.application.overload`

Test predicates:
- `test_global_capacity_exhaustion_remains_http_503`
- `test_subject_share_exhaustion_is_http_429_with_retry_after`

## `apps/api/tests/test_owner_restricted_pdf.py`

- SHA-256: `f100afc06f87feff0417687e000e6ead9920e1e00013545482f44620da60c3f2`
- Lines: 90
- Tests: 3
- KORPUS imports: `korpus.infrastructure.extraction`

Test predicates:
- `test_a_document_with_a_user_password_is_still_refused`
- `test_an_owner_restricted_document_is_read_and_the_restriction_recorded`
- `test_an_unencrypted_document_is_unaffected`

## `apps/api/tests/test_package_mode_integrity.py`

- SHA-256: `b6cb600524cc2c8d1b1ebb3ea011f04dfe4948192607481e8b745ffd6742fcd2`
- Lines: 61
- Tests: 2
- KORPUS imports: none

Test predicates:
- `test_package_verifier_accepts_preserved_executable_mode`
- `test_package_verifier_refuses_lost_executable_mode`

## `apps/api/tests/test_parser_sandbox_path.py`

- SHA-256: `de991dc195752598777b9be27e49727cfd1fbdfb7a3517e2d0ffcff70fb9b1bd`
- Lines: 107
- Tests: 3
- KORPUS imports: `korpus.infrastructure`

Test predicates:
- `test_a_relative_pythonpath_is_resolved_before_the_worker_sees_it`
- `test_an_empty_pythonpath_stays_empty`
- `test_every_entry_is_resolved_not_just_the_first`

## `apps/api/tests/test_permission_contract.py`

- SHA-256: `fb1ebccfe1a7f19d167f9e5bb6d4fb9297068d73bf5eb59304a937520ca1b0e7`
- Lines: 140
- Tests: 6
- KORPUS imports: `korpus.application.policy`, `korpus.domain.models`

Test predicates:
- `test_account_management_is_held_by_no_ordinary_role`
- `test_admin_wildcard_does_not_authorize_an_unknown_permission`
- `test_every_granted_permission_is_a_permission_the_system_names`
- `test_every_permission_a_route_requires_is_a_permission_the_system_names`
- `test_nothing_named_is_unreachable`
- `test_the_browser_reads_the_same_set_the_server_holds`

## `apps/api/tests/test_policy.py`

- SHA-256: `c4ea7591558f35cabeb55eaf7cff9dd1822cf10a2a6c26650629c4d69fbaab56`
- Lines: 24
- Tests: 3
- KORPUS imports: `korpus.application.policy`, `korpus.domain.models`

Test predicates:
- `test_identity_rejects_malformed_roles_and_corpus_ids`
- `test_requested_corpora_can_only_narrow_access`
- `test_role_permissions_are_fail_closed`

## `apps/api/tests/test_postgres_integration.py`

- SHA-256: `cd50ab6721cf2cb6a9284d2ba73062e89a18af0b290f3057a3dc9dbbf1ed6bf4`
- Lines: 160
- Tests: 1
- KORPUS imports: `korpus.application.retrieval`, `korpus.domain.models`, `korpus.infrastructure.repository`

Test predicates:
- `test_postgres_migrated_search_rls_access_and_audit`

## `apps/api/tests/test_postgres_role_grants.py`

- SHA-256: `9a92c314645b294489aeedfec91572bd957f4d9e8037ba52843d43bd03d3fcea`
- Lines: 90
- Tests: 3
- KORPUS imports: `korpus.infrastructure.ingestion_jobs`, `korpus.infrastructure.repository`

Test predicates:
- `test_a_table_is_classified_exactly_once`
- `test_every_application_table_is_granted_to_the_application_role`
- `test_no_grant_names_a_table_that_does_not_exist`

## `apps/api/tests/test_production_assurance.py`

- SHA-256: `221e73dbcc831238e5441b813b48396544fc70adf04bf69a35be0c584d21c0ea`
- Lines: 123
- Tests: 9
- KORPUS imports: `korpus.application.production_assurance`

Test predicates:
- `test_engineering_gate_uses_evidence_digest_not_git_digest_domain`
- `test_internal_redteam_cannot_promote_production`
- `test_non_postgres_backend_cannot_promote_production`
- `test_partial_mutation_scope_cannot_promote_production`
- `test_partial_supply_chain_evidence_cannot_promote_production`
- `test_production_assurance_requires_every_gate_and_external_evidence_class`
- `test_production_gate_generators_share_the_working_tree_digest_contract`
- `test_self_declared_external_redteam_without_trusted_attestation_is_rejected`
- `test_stale_gate_digest_is_rejected_even_if_it_says_pass`

## `apps/api/tests/test_production_assurance_cli.py`

- SHA-256: `73497ca5928a6b503c2c99161b1cdead9bd0dbe4d7c56251c081c20bf3657948`
- Lines: 34
- Tests: 1
- KORPUS imports: none

Test predicates:
- `test_production_assurance_cli_accepts_repo_relative_paths`

## `apps/api/tests/test_production_promotion_plumbing.py`

- SHA-256: `18ae660d6951c88313ffb7a59ccbbd3f4307386d3faf1a4c2c3d7bc40b2aaf69`
- Lines: 46
- Tests: 4
- KORPUS imports: none

Test predicates:
- `test_production_assurance_verifier_accepts_runtime_trust_only_through_shared_guard`
- `test_production_release_job_is_protected_tag_only_and_requires_external_roots`
- `test_production_release_script_requires_runtime_release_trust`
- `test_release_attestation_can_use_protected_runtime_trust`

## `apps/api/tests/test_production_reliability.py`

- SHA-256: `3338b99dbb264e0779c73560ae0f29362814c7fe1aaf12e26f98aebaf525e426`
- Lines: 91
- Tests: 6
- KORPUS imports: `korpus.application.assurance_evidence`, `korpus.application.production_reliability`

Test predicates:
- `test_complete_production_like_reliability_evidence_passes_base_predicates`
- `test_local_load_and_fixture_recovery_cannot_promote_production_even_if_signed`
- `test_pretrusted_attestations_clear_reliability_trust_boundary`
- `test_production_like_strings_without_attestations_cannot_promote_reliability`
- `test_reliability_evidence_from_another_tree_is_rejected`
- `test_signed_bad_load_cannot_pass_reliability_quality_predicates`

## `apps/api/tests/test_production_report_verification.py`

- SHA-256: `45ec9f2b2883a9677a453001ba28426d86a6c9e09877fc37b73108996627507f`
- Lines: 103
- Tests: 4
- KORPUS imports: `korpus.application.production_assurance`, `korpus.application.production_report_verification`

Test predicates:
- `test_forged_pass_report_cannot_override_failing_current_gate`
- `test_sound_recomputed_report_with_trusted_attestation_passes`
- `test_stale_gate_hashes_are_rejected_even_when_gate_payloads_match`
- `test_unsigned_or_untrusted_production_assurance_report_is_rejected`

## `apps/api/tests/test_query_cache.py`

- SHA-256: `7183a7d2ffe4d20d2f4f8e18bc4b3560db51f627d7173d872e291d8d1adf20d4`
- Lines: 100
- Tests: 3
- KORPUS imports: `korpus.application.cache`, `korpus.domain.models`

Test predicates:
- `test_cache_is_bound_to_identity_release_and_configuration`
- `test_cache_is_bounded_lru`
- `test_two_compartment_sets_do_not_share_a_cached_result`

## `apps/api/tests/test_query_planner_boundary.py`

- SHA-256: `5df793bf0fcbf2b5f1ee48edd04555381cde6c970e96c889ee0ee75518e8c19f`
- Lines: 196
- Tests: 8
- KORPUS imports: `korpus.api`, `korpus.application.query_plan`

Test predicates:
- `test_a_broken_planner_leaves_the_search_where_it_was`
- `test_a_defect_in_an_adapter_is_not_absorbed`
- `test_a_planner_that_blocks_does_not_hold_the_reader`
- `test_a_planner_that_returns_prose_contributes_nothing`
- `test_a_reformulation_finds_what_the_question_alone_did_not`
- `test_no_planner_is_the_same_as_a_planner_that_says_nothing`
- `test_the_answer_text_comes_only_from_the_corpus`
- `test_the_question_asked_is_always_the_first_search`

## `apps/api/tests/test_quote_provenance.py`

- SHA-256: `3f261d67954c1e97fa436792d6a4da96fd3a8d3bf028ad64acef3994914aa97c`
- Lines: 133
- Tests: 4
- KORPUS imports: `korpus.api.dependencies`, `korpus.application.answer_query`, `korpus.application.policy`, `korpus.application.risk`, `korpus.config`, `korpus.domain.models`, `korpus.infrastructure.extraction`

Test predicates:
- `test_a_quote_absent_from_its_span_stops_the_answer`
- `test_a_span_never_bridges_two_paragraphs_with_invented_separators`
- `test_an_answer_quotes_only_text_that_exists_in_the_document`
- `test_every_span_is_a_slice_of_its_page`

## `apps/api/tests/test_recovery_measurement.py`

- SHA-256: `9ced5ecf2a92ddf2e93af0027d972400b4a700dc501fbf232c1f9a057a46a7dc`
- Lines: 117
- Tests: 8
- KORPUS imports: `korpus.application.recovery`

Test predicates:
- `test_a_duration_without_provenance_is_not_a_measurement`
- `test_a_fixture_cannot_promote_itself_by_editing_a_string`
- `test_a_production_scale_claim_is_allowed_once_the_provenance_carries_it`
- `test_a_report_with_no_duration_is_incomplete`
- `test_an_honest_fixture_report_is_accepted_and_still_says_what_it_is_not`
- `test_an_unrecognised_scale_class_is_not_believed`
- `test_no_report_is_not_a_pass`
- `test_zero_loss_without_writes_after_the_backup_is_not_a_measurement`

## `apps/api/tests/test_reference_set.py`

- SHA-256: `97355d5f2e868dc1479447de412186aa1f086321278796675ea26ba33acaf041`
- Lines: 118
- Tests: 6
- KORPUS imports: none

Test predicates:
- `test_a_retrieval_case_names_every_version_that_holds_its_sentence`
- `test_every_stratum_is_represented_and_none_dominates`
- `test_no_case_is_a_table_of_contents`
- `test_refusal_cases_were_verified_absent_rather_than_assumed_absent`
- `test_the_set_is_frozen_with_a_digest_over_its_own_cases`
- `test_the_set_says_what_it_cannot_judge`

## `apps/api/tests/test_release_attestation_trust.py`

- SHA-256: `c910e2fac6bc59e186126d15b6d88c53ea94719987f8ad769612429653bb2372`
- Lines: 23
- Tests: 1
- KORPUS imports: none

Test predicates:
- `test_release_attestation_requires_pretrusted_signer`

## `apps/api/tests/test_release_eval_corpus_v2.py`

- SHA-256: `849183ead6508ca40900399d737c47eeeafff0286ccd51af99fd22bb81b749ae`
- Lines: 79
- Tests: 4
- KORPUS imports: none

Test predicates:
- `test_adversarial_retrieval_vectors_never_authorize_document_instructions`
- `test_package_vectors_are_negative_controls_not_acceptance_examples`
- `test_release_eval_manifest_binds_every_dataset_byte`
- `test_release_eval_rows_have_unique_ids_and_required_safety_fields`

## `apps/api/tests/test_release_identity.py`

- SHA-256: `0d80d6cfef656d9299521e0774267b2c6cfd0d94925adb30a7e315c38526964f`
- Lines: 40
- Tests: 2
- KORPUS imports: none

Test predicates:
- `test_current_release_identity_surfaces_agree`
- `test_release_identity_covers_handoff_and_package_surfaces`

## `apps/api/tests/test_release_state_machine.py`

- SHA-256: `d1593b6e583c313e93f37192899ac000457bbbb9fa8185dff7f2af3eb05f1328`
- Lines: 175
- Tests: 10
- KORPUS imports: `korpus.application.assurance_calculus`, `korpus.application.release_state_machine`

Test predicates:
- `test_authorized_release_cannot_move_back_to_candidate`
- `test_candidate_requires_mutation_negative_control`
- `test_draft_to_integrated_does_not_require_assurance_gate_yet`
- `test_full_gate_set_and_independent_verifier_authorize_production`
- `test_production_authorization_requires_independent_verifier`
- `test_promotion_must_be_sequential`
- `test_release_identity_digest_is_deterministic_and_domain_separated`
- `test_release_identity_rejects_non_sha_digests`
- `test_verified_requires_verifier_and_exact_source_bound_gate`
- `test_withdrawal_is_the_only_general_safety_escape`

## `apps/api/tests/test_reliability_degradation.py`

- SHA-256: `6bcc09eb89ef105abdff13221f0ff4e08ff2b0800c93c031b9819dce3c000720`
- Lines: 229
- Tests: 6
- KORPUS imports: `korpus.api.routes_corpus`, `korpus.application.policy`, `korpus.application.ports`, `korpus.config`, `korpus.domain.models`, `korpus.infrastructure.ingestion_jobs`, `korpus.infrastructure.object_store`, `korpus.infrastructure.repository`, `korpus.main`, `korpus.security.auth`

Test predicates:
- `test_a_caller_error_is_not_disguised_as_an_outage`
- `test_a_crashed_worker_leaves_no_zombie_running_job`
- `test_a_full_upload_spool_is_a_503_not_a_500`
- `test_a_transient_object_store_error_becomes_a_typed_retryable_failure`
- `test_database_down_is_a_503_not_a_500`
- `test_object_store_unavailable_is_a_503_not_a_500`

## `apps/api/tests/test_repository_access_refusals.py`

- SHA-256: `72e2bcf3f6a7f8260fc24bf5afbeda5ca80e7376f85883bd0724404e9ac153d0`
- Lines: 319
- Tests: 15
- KORPUS imports: `korpus.application.ingestion`, `korpus.application.ingestion_jobs`, `korpus.application.policy`, `korpus.composition`, `korpus.domain.models`, `korpus.infrastructure.ingestion_jobs`, `korpus.infrastructure.object_store`, `korpus.infrastructure.repository`

Test predicates:
- `test_a_document_that_does_not_exist_is_absent_rather_than_an_error`
- `test_a_hash_lookup_is_scoped_to_the_corpus_when_one_is_given`
- `test_a_hash_lookup_is_scoped_to_the_document_when_one_is_given`
- `test_a_malformed_fingerprint_is_refused`
- `test_a_reviewer_cannot_transition_a_version_from_another_corpus`
- `test_a_similarity_threshold_outside_the_supported_range_is_refused`
- `test_a_version_cannot_be_queued_against_a_document_in_another_corpus`
- `test_an_entitled_identity_reads_the_document`
- `test_bytes_nobody_uploaded_are_not_found`
- `test_get_document_returns_the_row_and_leaves_the_decision_to_the_caller`
- `test_identical_bytes_under_a_different_revision_are_a_different_version`
- `test_listing_hides_a_document_above_the_readers_clearance`
- `test_listing_hides_documents_from_a_corpus_the_identity_does_not_hold`
- `test_near_duplicate_search_finds_the_version_for_an_entitled_identity`
- `test_near_duplicate_search_is_scoped_to_the_corpora_the_identity_holds`

## `apps/api/tests/test_repository_noninterference.py`

- SHA-256: `44b7a13d8c41115ea5df9c3d4a26342f99472fcf7aa4cb155ce02c1d27c77fb9`
- Lines: 39
- Tests: 1
- KORPUS imports: `korpus.application.retrieval`

Test predicates:
- `test_public_candidate_scores_are_unchanged_by_restricted_corpus`

## `apps/api/tests/test_repository_register.py`

- SHA-256: `3edc039da311afeb6a76904ba985b5a2daab9b6de668d470dd7f88568cf9d0ca`
- Lines: 135
- Tests: 11
- KORPUS imports: `korpus.repository_requirements`

Test predicates:
- `test_a_clean_tree_reports_nothing`
- `test_a_file_at_the_limit_is_not_flagged`
- `test_a_plaintext_secret_in_the_tree_is_detected`
- `test_a_secret_git_does_track_is_still_reported`
- `test_a_secret_git_ignores_is_not_reported_as_tracked`
- `test_a_secret_outside_the_secrets_directory_is_not_flagged`
- `test_a_todo_implement_comment_is_detected`
- `test_an_oversized_file_is_detected`
- `test_an_unparseable_contract_is_recorded`
- `test_an_unresolved_placeholder_is_detected`
- `test_ignored_directories_are_not_walked`

## `apps/api/tests/test_repository_seams.py`

- SHA-256: `1cd882049c64b65e7cadc9c654a6200c822b6efd2c51753fca06bfc84d802d51`
- Lines: 185
- Tests: 9
- KORPUS imports: `korpus.domain.models`, `korpus.infrastructure`, `korpus.infrastructure.repository`

Test predicates:
- `test_a_query_with_no_usable_term_returns_no_statement`
- `test_a_reader_with_no_compartments_still_gets_the_compartment_predicate`
- `test_an_unsupported_dialect_refuses_rather_than_returning_a_broken_statement`
- `test_the_candidate_query_binds_the_readers_clearance_rather_than_a_constant`
- `test_the_projection_carries_every_access_predicate_it_is_supposed_to`
- `test_the_query_builders_never_open_a_connection`
- `test_the_repository_delegates_rather_than_keeping_a_second_copy`
- `test_the_schema_module_does_not_import_what_reads_it`
- `test_the_schema_still_answers_to_its_old_name`

## `apps/api/tests/test_reproducibility.py`

- SHA-256: `7123a56a9c096067ac369f944ebbc7b1a6ec12366a7da19e004eebf23f3acdd3`
- Lines: 20
- Tests: 1
- KORPUS imports: none

Test predicates:
- `test_corpus_release_changes_only_for_accessible_approved_state`

## `apps/api/tests/test_requirement_registry.py`

- SHA-256: `71781c55aa82298c4e49043166eebbb2d387a5845ef1acce2e6727391edf07cd`
- Lines: 378
- Tests: 20
- KORPUS imports: `korpus.application.deployment`, `korpus.application.requirements`, `korpus.controlled_requirements`, `korpus.infrastructure_requirements`, `korpus.kubernetes_requirements`, `korpus.repository_requirements`

Test predicates:
- `test_a_deployed_configuration_that_drifts_from_policy_is_reported`
- `test_a_failure_names_one_container_of_one_workload`
- `test_a_missing_configmap_reports_every_required_key`
- `test_a_predicate_that_raises_fails_its_own_requirement`
- `test_all_requirements_are_evaluated_not_just_up_to_the_first_failure`
- `test_an_empty_render_reports_one_failure_rather_than_the_whole_register`
- `test_duplicate_ids_are_actually_detected`
- `test_every_required_service_carries_the_full_hardening_set`
- `test_every_requirement_has_a_unique_id`
- `test_every_requirement_names_a_subject_and_states_something`
- `test_every_requirement_states_a_property_rather_than_a_complaint`
- `test_ids_are_unique_across_every_register`
- `test_no_requirement_is_stated_twice_under_two_ids`
- `test_one_walk_answers_every_filesystem_question`
- `test_the_kubernetes_register_states_the_same_rules_as_the_gate`
- `test_the_load_bearing_requirements_survived_the_move`
- `test_the_register_reads_as_a_document`
- `test_the_report_carries_the_id_and_the_reason`
- `test_the_shipped_infrastructure_register_is_satisfied`
- `test_the_shipped_repository_register_is_satisfied`

## `apps/api/tests/test_rescission_and_clock.py`

- SHA-256: `8ec17f76af76577e7b06c969fbe1dd798a88e7d74d98edcedc4bceeb4a39b103`
- Lines: 172
- Tests: 7
- KORPUS imports: `korpus.domain.models`

Test predicates:
- `test_an_approved_order_can_be_withdrawn`
- `test_an_unapproved_version_cannot_be_withdrawn`
- `test_the_default_as_of_does_not_depend_on_the_host_timezone`
- `test_withdrawal_is_dated_and_the_day_before_still_answers`
- `test_withdrawal_is_recorded_in_the_audit_chain`
- `test_withdrawal_requires_the_approval_permission`
- `test_withdrawing_twice_is_refused_as_already_withdrawn`

## `apps/api/tests/test_resilience.py`

- SHA-256: `72a7e088cb158e8329a06a3b9e714bed6e09409877c14f8c5484d0f46ca5326e`
- Lines: 54
- Tests: 2
- KORPUS imports: `korpus.application.resilience`

Test predicates:
- `test_admission_controller_is_bounded_and_recovers`
- `test_circuit_breaker_opens_then_half_open_probe_recovers`

## `apps/api/tests/test_resilience_and_audit_scope.py`

- SHA-256: `3d29f36ec24d48ae2ca1f3be37aeff126d7466bab5fb8a08859de86f8fec5051`
- Lines: 171
- Tests: 10
- KORPUS imports: `korpus.application.resilience`, `korpus.domain.models`, `korpus.infrastructure.repository`

Test predicates:
- `test_a_default_share_leaves_room_for_someone_else`
- `test_a_malformed_trace_id_is_refused`
- `test_a_rejected_subject_does_not_leak_its_slot`
- `test_an_auditor_reads_the_events_of_one_request`
- `test_healthcheck_fails_on_a_corrupt_database`
- `test_one_subject_cannot_take_the_whole_service`
- `test_reading_the_audit_requires_the_audit_permission`
- `test_the_per_subject_share_is_returned_when_the_work_finishes`
- `test_the_subject_table_does_not_grow_without_bound`
- `test_the_trace_scope_excludes_other_requests`

## `apps/api/tests/test_retention_planning.py`

- SHA-256: `70f39d813b8d58d57f2b3cfad5d5c8ac9b543874bbe9659c0ca26eeeb5ad1ce2`
- Lines: 172
- Tests: 12
- KORPUS imports: `korpus.application.retention`, `korpus.domain.models`, `korpus.security.corpus_governance`

Test predicates:
- `test_a_corpus_with_no_policy_is_ungoverned_rather_than_assumed_safe`
- `test_a_document_inside_its_retention_period_is_retained`
- `test_a_document_past_its_period_in_a_corpus_that_permits_deletion_is_eligible`
- `test_a_document_past_its_period_without_delete_permission_awaits_a_decision`
- `test_legal_hold_outranks_the_retention_period`
- `test_naive_timestamps_are_treated_as_utc_rather_than_raising`
- `test_reconciliation_is_silent_when_the_plan_matches_storage`
- `test_reconciliation_reports_held_material_that_has_already_gone`
- `test_reconciliation_reports_material_the_plan_never_saw`
- `test_the_boundary_day_is_still_retained`
- `test_the_governance_profile_refuses_delete_together_with_legal_hold`
- `test_the_serialised_plan_counts_every_disposition`

## `apps/api/tests/test_retrieval_budget_semantics.py`

- SHA-256: `3a1e6584034d45c4e7f6e3bccce3be5ee617512238ce5f472368e16c20e8c491`
- Lines: 142
- Tests: 3
- KORPUS imports: `korpus.application.retrieval`, `korpus.domain.models`

Test predicates:
- `test_an_overrun_that_found_candidates_returns_them`
- `test_an_overrun_with_nothing_found_is_still_refused`
- `test_nothing_found_within_budget_is_an_empty_answer_not_a_refusal`

## `apps/api/tests/test_retrieval_properties.py`

- SHA-256: `a809f7f1f8f6b579156cc95aab3219d6f95153cdbcec0d850a66ffbdd76a24b0`
- Lines: 57
- Tests: 5
- KORPUS imports: `korpus.application.retrieval`

Test predicates:
- `test_character_ngrams_are_deterministic_and_nonempty_for_text`
- `test_irrelevant_documents_do_not_displace_exact_relevant_document`
- `test_retrieval_ranking_is_permutation_invariant_for_unique_scores`
- `test_score_bounds_hold_over_seeded_random_inputs`
- `test_tokenization_is_unicode_and_case_normalization_invariant`

## `apps/api/tests/test_retrieval_supersession_cost.py`

- SHA-256: `857e61b35a8c485a3b8ff7700d651725a00598ced5f4ba0a06796abdc51a9d23`
- Lines: 115
- Tests: 3
- KORPUS imports: `korpus.domain.models`, `korpus.infrastructure.retrieval_queries`

Test predicates:
- `test_both_dialects_gather_the_superseded_set_once`
- `test_the_plan_is_read_from_a_statement_that_actually_parses`
- `test_the_supersession_test_is_not_evaluated_per_matching_span`

## `apps/api/tests/test_retriever_scope.py`

- SHA-256: `d8c3073eae5b2d9f2a8ae837d0d89fec29d4f6a4334bb15bebb7ac7abfce7a95`
- Lines: 222
- Tests: 4
- KORPUS imports: `korpus.api.dependencies`, `korpus.application.answer_query`, `korpus.application.policy`, `korpus.domain.models`, `korpus.infrastructure.repository`

Test predicates:
- `test_in_scope_evidence_still_answers`
- `test_one_out_of_scope_row_stops_an_otherwise_valid_batch`
- `test_out_of_scope_evidence_stops_the_answer`
- `test_the_breach_is_written_to_the_audit_chain`

## `apps/api/tests/test_reviewer_registry.py`

- SHA-256: `49b1e2277a60243a9182e511d76d451ec0ab22b95607e75f619eaeb76cfa7900`
- Lines: 192
- Tests: 3
- KORPUS imports: `korpus.application.ingestion`, `korpus.application.policy`, `korpus.composition`, `korpus.domain.models`, `korpus.infrastructure.object_store`, `korpus.infrastructure.repository`, `korpus.security.reviewers`

Test predicates:
- `test_governed_review_records_stage_specific_credential_ids`
- `test_registry_digest_revocation_and_scope_are_fail_closed`
- `test_required_registry_cannot_be_omitted`

## `apps/api/tests/test_risk_policy.py`

- SHA-256: `ffe2a1ca8908c4ed82917edfc9e9a3db2886195e75e08d2b99c920b58c913a5e`
- Lines: 35
- Tests: 3
- KORPUS imports: `korpus.application.answer_query`, `korpus.application.risk`, `korpus.domain.models`

Test predicates:
- `test_answer_policy_exposes_no_authority_bypass`
- `test_query_risk_classifier_is_deterministic_and_conservative`
- `test_risk_thresholds_are_monotone`

## `apps/api/tests/test_risk_rules.py`

- SHA-256: `a2aa98bf8ae8ccbdad635715d5000aa6c041d288ac888b32145dfa36ebeeae5e`
- Lines: 162
- Tests: 13
- KORPUS imports: `korpus.application.risk`, `korpus.application.risk_rules`

Test predicates:
- `test_a_rephrased_operational_question_is_still_operational`
- `test_an_unrecognised_query_is_unclassified_not_standard`
- `test_every_rule_carries_at_least_one_example`
- `test_every_rule_matches_its_own_examples`
- `test_every_rule_states_why_it_exists`
- `test_no_rule_fires_on_its_own_counterexamples`
- `test_operational_outranks_temporal_when_both_apply`
- `test_rule_ids_are_unique`
- `test_the_corpus_of_examples_is_large_enough_to_mean_something`
- `test_the_deciding_rule_travels_with_the_class`
- `test_unclassified_costs_less_than_operational`
- `test_unclassified_costs_more_than_standard`
- `test_unclassified_raises_evidence_but_not_relevance`

## `apps/api/tests/test_routes_permissions.py`

- SHA-256: `b3e54a4aeda03e0d460f7366f30093e2716a50403c63d73eed3550ae88f5ef91`
- Lines: 41
- Tests: 2
- KORPUS imports: `korpus.domain.models`

Test predicates:
- `test_document_and_audit_routes_are_denied_without_permissions`
- `test_ingest_rejects_empty_file`

## `apps/api/tests/test_row_mapping.py`

- SHA-256: `277d91620655608ca3342d941ce27620e4a41849568c00f26cdba169ebc9b20f`
- Lines: 144
- Tests: 9
- KORPUS imports: `korpus.domain.models`, `korpus.infrastructure`, `korpus.infrastructure.repository`

Test predicates:
- `test_a_document_survives_the_round_trip`
- `test_a_naive_timestamp_is_read_as_utc`
- `test_an_aware_timestamp_keeps_its_offset`
- `test_clearance_widens_the_classifications_it_may_read`
- `test_compartments_survive_as_a_set_not_a_string`
- `test_review_state_and_authority_come_back_as_enums`
- `test_the_base_mapper_refuses_a_projection_row`
- `test_the_projection_mapper_reads_the_joined_column_names`
- `test_the_repository_uses_these_functions_rather_than_copies`

## `apps/api/tests/test_runtime_factory.py`

- SHA-256: `9bf5f05faea58f3d419b6179ffac1d2b62770754f99958a5de5dc24f5fa199dd`
- Lines: 21
- Tests: 1
- KORPUS imports: `korpus.config`, `korpus.infrastructure.audit_anchor`, `korpus.infrastructure.object_store`, `korpus.infrastructure.runtime`

Test predicates:
- `test_runtime_factories_share_configuration_and_do_not_recreate_defaults`

## `apps/api/tests/test_s3_object_store.py`

- SHA-256: `5d171414a32a088b58cb6e7ee56a68d6b92b8f0bc7ed07c8e4c7d592ce963b50`
- Lines: 95
- Tests: 5
- KORPUS imports: `korpus.infrastructure.object_store`

Test predicates:
- `test_s3_healthcheck_requires_versioning_and_object_lock_when_retention_enabled`
- `test_s3_healthchecks_application_prefix_permission`
- `test_s3_store_is_content_addressed_idempotent_and_integrity_checked`
- `test_s3_store_rejects_hash_mismatch`
- `test_s3_store_rejects_unsafe_prefix_and_bounded_reads`

## `apps/api/tests/test_schema_revision_pin.py`

- SHA-256: `761588e566ceded11811217b06c32862cba20263fa639157ec7a5ed3b9785166`
- Lines: 83
- Tests: 3
- KORPUS imports: `korpus.infrastructure.repository`

Test predicates:
- `test_every_revision_except_the_first_has_a_parent_that_exists`
- `test_the_code_pins_the_head_of_the_migration_graph`
- `test_the_migration_graph_has_exactly_one_head`

## `apps/api/tests/test_search_index.py`

- SHA-256: `07d8227c757b176b5c4245d8d8c3a9d2f0efc9f2595d8467deebc2e9d95de02e`
- Lines: 47
- Tests: 2
- KORPUS imports: `korpus.application.retrieval`

Test predicates:
- `test_database_candidate_budget_is_a_hard_upper_bound`
- `test_retrieval_uses_database_candidate_index_not_full_scan`

## `apps/api/tests/test_security_auth_api.py`

- SHA-256: `cf5edd54fc5c3da269acf5cfaee93ad6fa476272d25fa3bee2df4da8f8386aed`
- Lines: 81
- Tests: 2
- KORPUS imports: `korpus.config`, `korpus.domain.models`, `korpus.main`, `korpus.security.auth`

Test predicates:
- `test_every_nonpublic_v1_route_depends_on_identity`
- `test_jwt_auth_accepts_valid_token_and_rejects_invalid`

## `apps/api/tests/test_semantic_integration.py`

- SHA-256: `1406c8b8aaa5fc2f02a9b9f09068efe4b0efec5903fd20dbaa8c61dfd9093a91`
- Lines: 138
- Tests: 6
- KORPUS imports: `korpus.application.retrieval`, `korpus.domain.models`, `korpus.infrastructure.semantic`

Test predicates:
- `test_embedding_provider_configuration_is_fail_closed`
- `test_pgvector_index_ddl_is_deterministic_partial_and_bounded`
- `test_postgres_rls_migration_is_default_deny_when_context_is_absent`
- `test_repository_protocol_can_materialize_authorized_semantic_ids`
- `test_required_semantic_failure_never_silently_falls_back_to_lexical`
- `test_semantic_candidates_are_authorized_materialized_and_fused`

## `apps/api/tests/test_service_objectives.py`

- SHA-256: `61ad1cf19592dbd02bda305760e18b2f3bb844e27bb9480226b9489ee02f2135`
- Lines: 158
- Tests: 7
- KORPUS imports: none

Test predicates:
- `test_a_healthy_measurement_meets_every_objective`
- `test_a_server_error_fails_the_objective`
- `test_an_unfinished_search_fails_the_objective`
- `test_every_objective_carries_the_conditions_it_was_judged_under`
- `test_latency_beyond_the_objective_fails`
- `test_no_measurement_is_unmeasured_and_not_a_pass`
- `test_subject_throttling_under_rated_load_fails_capacity_objective`

## `apps/api/tests/test_snapshot_refuses_stale_evidence.py`

- SHA-256: `1bbd59cb4e2d308ca4007c7a032647facae19b2d804f09c1a5baef57126898a8`
- Lines: 102
- Tests: 4
- KORPUS imports: none

Test predicates:
- `test_a_gate_without_evidence_digests_cannot_be_trusted`
- `test_a_missing_hashed_artifact_is_refused`
- `test_a_promoted_file_the_gate_did_not_hash_is_refused`
- `test_matching_evidence_is_accepted`

## `apps/api/tests/test_source_signature_refusals.py`

- SHA-256: `827675812eac10263869364ba0895425048e9b1adf9e454a67303ee2be078b73`
- Lines: 225
- Tests: 16
- KORPUS imports: `korpus.domain.models`, `korpus.security.source_authenticity`

Test predicates:
- `test_a_correctly_signed_version_is_accepted`
- `test_a_key_belonging_to_another_issuer_is_refused`
- `test_a_key_not_authorised_for_the_declared_authority_class_is_refused`
- `test_a_key_with_no_authority_restriction_signs_any_class`
- `test_a_profile_whose_map_disagrees_with_its_key_ids_is_refused`
- `test_a_public_key_of_the_wrong_length_is_refused`
- `test_a_revoked_key_is_refused_even_though_the_signature_verifies`
- `test_a_signature_after_the_key_expired_is_refused`
- `test_a_signature_before_the_key_existed_is_refused`
- `test_a_signature_from_an_unknown_key_is_refused`
- `test_a_signature_over_a_different_source_hash_is_refused`
- `test_a_signature_over_altered_metadata_is_refused`
- `test_a_version_without_a_signature_is_refused`
- `test_an_empty_trust_profile_is_refused`
- `test_an_inverted_validity_interval_is_refused`
- `test_effective_from_stands_in_when_there_is_no_publication_date`

## `apps/api/tests/test_span_lookup.py`

- SHA-256: `232bda40e37594a4f33b6e2126c7a34ff2651e5b75e1b1438948886e348aa812`
- Lines: 181
- Tests: 6
- KORPUS imports: `korpus.domain.models`

Test predicates:
- `test_a_reader_cannot_open_a_span_they_could_not_have_been_cited`
- `test_a_span_carries_the_section_it_sits_under`
- `test_a_span_is_not_disclosed_on_a_date_the_version_did_not_govern`
- `test_listing_one_version_does_not_read_the_whole_corpus`
- `test_the_answer_citation_resolves_to_a_span_that_contains_the_quote`
- `test_the_spans_of_a_version_can_be_listed`

## `apps/api/tests/test_sqlite_recovery_contract.py`

- SHA-256: `fd687d8cab51e30522768ea2a3ecd65e6c2398bb8693a6d06d5678c772c6b949`
- Lines: 36
- Tests: 3
- KORPUS imports: `korpus.config`

Test predicates:
- `test_recovery_measurement_uses_latest_protected_write_not_audit_only`
- `test_sqlite_recovery_drill_is_fail_honest_about_fixture_class`
- `test_sqlite_recovery_environment_names_are_declared_operational_variables`

## `apps/api/tests/test_state_machine.py`

- SHA-256: `73f0a46f10de31c912806847dfb5074c9738314cd325a204fc8be20fc9342477`
- Lines: 130
- Tests: 3
- KORPUS imports: `korpus.application.ingestion`, `korpus.config`, `korpus.domain.models`, `korpus.main`, `korpus.security.auth`

Test predicates:
- `test_approval_is_reachable_only_through_both_review_stages`
- `test_controlled_review_separation_is_subject_based`
- `test_review_state_machine_has_no_path_out_of_rejected`

## `apps/api/tests/test_status_document_matches_the_registers.py`

- SHA-256: `3198a2a889f0f67e01ef3150cd697840b65717410be24b519f2928d01cae7d0a`
- Lines: 70
- Tests: 5
- KORPUS imports: none

Test predicates:
- `test_the_document_is_not_stale`
- `test_the_document_never_claims_production_authorization`
- `test_the_external_debt_count_is_the_register_count`
- `test_the_open_grounds_count_excludes_the_can_go_red_ground`
- `test_the_v5_snapshot_says_it_is_frozen`

## `apps/api/tests/test_structured_evidence_and_fuzz.py`

- SHA-256: `f62d797627d1580772fc16179f0d058bece9c5af3ae0329dceeb5d5d8795c9c7`
- Lines: 85
- Tests: 5
- KORPUS imports: `korpus.application.evidence`, `korpus.infrastructure`

Test predicates:
- `test_fake_and_truncated_pdf_fuzz_fails_closed`
- `test_numbers_units_tables_and_formulae_remain_citable`
- `test_numeric_unit_conflicts_are_detected_without_cross_unit_false_positive`
- `test_sentence_offsets_preserve_decimals_abbreviations_and_rows`
- `test_text_html_json_parser_seeded_fuzz_is_bounded`

## `apps/api/tests/test_supply_chain_evidence_boundary.py`

- SHA-256: `1fda4a7f564209f981bb35b0b75367e5871c7bd57c4a2c015c4f4cb740e564b4`
- Lines: 88
- Tests: 9
- KORPUS imports: `korpus.application.assurance_evidence`, `korpus.application.supply_chain_scanners`

Test predicates:
- `test_container_sbom_filename_without_cyclonedx_payload_is_not_evidence`
- `test_container_scan_marker_requires_both_image_scans_exit_zero`
- `test_scanner_marker_commit_must_match_current_pipeline_commit`
- `test_scanner_summary_requires_every_declared_scanner_exit_zero`
- `test_scanner_summary_status_string_alone_is_not_clean`
- `test_source_sbom_must_cover_every_locked_component`
- `test_supply_chain_manifest_from_another_source_tree_is_rejected`
- `test_supply_chain_manifest_is_bound_to_artifact_bytes`
- `test_supply_chain_manifest_rejects_unverified_extra_artifact`

## `apps/api/tests/test_support_gate.py`

- SHA-256: `c6257d54fff64fe2ce8b25172bb63116e25fe7cea4a353f5c494af2fe5f15d04`
- Lines: 166
- Tests: 6
- KORPUS imports: `korpus.api.dependencies`, `korpus.application.answer_query`, `korpus.application.evidence`, `korpus.application.policy`, `korpus.application.risk`, `korpus.config`

Test predicates:
- `test_a_claim_that_drifts_from_its_span_is_dropped`
- `test_a_claim_the_span_does_not_carry_is_not_fully_supported`
- `test_a_verbatim_extract_is_fully_supported`
- `test_an_empty_claim_has_no_support`
- `test_the_extraction_step_drops_a_claim_below_the_support_threshold`
- `test_the_extraction_step_keeps_an_exact_extract`

## `apps/api/tests/test_system_manifest_exclusions.py`

- SHA-256: `bb9c7517f2e91858f45e94acc6d304940ca5be191bc520dabd52dcfca7abcb04`
- Lines: 22
- Tests: 1
- KORPUS imports: none

Test predicates:
- `test_generated_handoff_evidence_is_not_part_of_system_manifest_or_source_digest`

## `apps/api/tests/test_table_integrity.py`

- SHA-256: `2815a75ef5449cb8a8c946196aaebaa3e2e5cf879f600fa01f450fe0b1bb33c6`
- Lines: 129
- Tests: 10
- KORPUS imports: `korpus.application.extraction_quality`, `korpus.application.table_integrity`

Test predicates:
- `test_a_block_of_text_rows_without_digits_is_not_a_table`
- `test_a_line_with_several_numbers_is_not_a_row_without_column_gaps`
- `test_a_row_that_lost_a_column_is_flagged`
- `test_a_table_that_kept_its_shape_is_not_flagged`
- `test_ordinary_prose_is_not_a_table`
- `test_samples_are_bounded`
- `test_table_damage_reaches_the_reviewer_through_the_extraction_quality_gate`
- `test_two_rows_are_not_enough_to_judge_a_shape`
- `test_two_tables_separated_by_prose_are_judged_separately`
- `test_wrapped_prose_with_single_spaces_is_not_a_table`

## `apps/api/tests/test_telemetry_status.py`

- SHA-256: `7ea87cac4f7737cafb1e1857a1962ee8c993e5df61a4bf6e42aa1d1d65eed2bc`
- Lines: 75
- Tests: 4
- KORPUS imports: `korpus.infrastructure.observability`

Test predicates:
- `test_a_configured_endpoint_that_could_not_be_attached_says_so`
- `test_metrics_remain_available_regardless_of_trace_export`
- `test_telemetry_is_reported_as_disabled_when_no_endpoint_is_configured`
- `test_the_requested_endpoint_is_retained_for_diagnosis`

## `apps/api/tests/test_tenancy_api.py`

- SHA-256: `26ff68f61d35bc53ec4284dd0731949eb310e79a967d21cd0117e38a533f9091`
- Lines: 410
- Tests: 18
- KORPUS imports: `korpus.application.answer_query`, `korpus.application.paid_access`, `korpus.application.resilience`, `korpus.config`, `korpus.domain.models`, `korpus.domain.tenancy`, `korpus.main`, `korpus.security.auth`

Test predicates:
- `test_a_disabled_account_is_refused_everywhere`
- `test_a_question_inside_a_conversation_is_answered_and_recorded`
- `test_a_shed_question_is_kept_and_no_answer_is_invented_under_it`
- `test_an_inactive_subscription_is_refused_before_retrieval_runs`
- `test_an_unknown_conversation_id_is_a_404_not_a_500`
- `test_another_account_gets_404_for_a_conversation_it_does_not_own`
- `test_conversations_are_created_listed_and_archived`
- `test_starting_a_subscription_never_produces_an_active_one`
- `test_the_account_endpoint_creates_on_first_call_and_is_stable`
- `test_the_conversation_route_sheds_load_like_the_stateless_one`
- `test_the_entitlement_endpoint_says_whether_it_is_enforced`
- `test_the_list_endpoint_says_when_it_truncated`
- `test_the_openapi_document_describes_the_new_surface`
- `test_the_page_bounds_are_enforced_by_the_contract`
- `test_the_transcript_carries_the_verdict_the_reader_was_shown`
- `test_the_webhook_applies_a_signed_event_without_any_session`
- `test_the_webhook_refuses_an_oversized_body_at_the_http_boundary`
- `test_the_webhook_refuses_an_unsigned_body`

## `apps/api/tests/test_tenancy_audit_events.py`

- SHA-256: `109645a0d49f8b626b2404a01a99c7735472df6d42b5d361f40cddb79c7b3c0e`
- Lines: 199
- Tests: 5
- KORPUS imports: `korpus.application.policy`, `korpus.infrastructure.repository`, `korpus.infrastructure.tenancy_repository`

Test predicates:
- `test_a_billing_event_is_recorded_by_hash_and_never_by_body`
- `test_a_rejected_event_is_recorded_with_the_reason_it_was_rejected`
- `test_an_audit_actor_holds_no_reading_rights`
- `test_every_state_change_appends_its_own_audit_event`
- `test_no_audit_payload_carries_a_secret_or_a_customer_detail`

## `apps/api/tests/test_tenancy_migration.py`

- SHA-256: `c1d04346dc66e800e78807a2daa676564990178a3675e13ad2babc7894607b04`
- Lines: 238
- Tests: 6
- KORPUS imports: `korpus.infrastructure.schema`

Test predicates:
- `test_a_clean_database_migrates_to_the_pinned_head`
- `test_a_disabled_account_without_a_timestamp_is_refused_by_the_database`
- `test_sellable_plan_price_pair_is_enforced_by_the_migrated_schema`
- `test_the_unique_constraints_are_enforced_by_the_migrated_schema`
- `test_the_upgrade_can_be_reversed`
- `test_upgrading_from_the_previous_release_preserves_the_corpus`

## `apps/api/tests/test_tenancy_threats.py`

- SHA-256: `f7c6466a5d0cd5f9cf1f1503a8e7e78cd3bb94f0bc2e04ef42a6a052d5810dae`
- Lines: 376
- Tests: 16
- KORPUS imports: `korpus.api`, `korpus.api.request_limits`, `korpus.application.accounts`, `korpus.application.egress`, `korpus.application.paid_access`, `korpus.application.policy`, `korpus.application.ports`, `korpus.application.query_plan`, `korpus.application.tenancy_ports`, `korpus.domain.models`, `korpus.domain.tenancy`, `korpus.infrastructure`, `korpus.infrastructure.anthropic_planner`

Test predicates:
- `test_a_denial_is_not_a_silent_pass`
- `test_every_named_threat_class_has_a_test`
- `test_t01_a_forged_billing_event_cannot_activate_a_plan`
- `test_t02_a_replayed_event_is_a_duplicate_and_an_old_one_is_refused`
- `test_t03_a_canceled_subscription_cannot_be_resurrected`
- `test_t04_no_request_field_can_assert_that_a_subscription_is_paid`
- `test_t05_a_plan_cannot_escalate_beyond_the_identity`
- `test_t06_another_accounts_conversation_is_unreachable_by_id`
- `test_t07_a_foreign_id_and_a_nonexistent_id_are_indistinguishable`
- `test_t08_disabling_takes_effect_on_the_next_request_not_the_next_login`
- `test_t09_an_identity_provider_cannot_grant_corpora_through_a_claim`
- `test_t10_a_prior_answer_is_stored_as_an_answer_and_not_as_a_source`
- `test_t11_a_restricted_deployment_does_not_send_the_question_anywhere`
- `test_t12_an_unbounded_webhook_body_is_refused_before_it_is_parsed`
- `test_t12a_declared_oversize_is_refused_before_stream_consumption`
- `test_t12b_chunked_oversize_stops_at_the_first_excess_chunk`

## `apps/api/tests/test_tevv_admissibility.py`

- SHA-256: `90d838c6713aae28ba251c3aa99e7f57c46631bf1ab74de17c67f6996858d559`
- Lines: 134
- Tests: 8
- KORPUS imports: `korpus.application.tevv`

Test predicates:
- `test_a_corpus_that_declares_itself_synthetic_is_refused`
- `test_a_declared_corpus_with_enough_observations_is_admissible`
- `test_a_perfect_score_is_not_certainty`
- `test_a_wide_interval_is_refused_even_on_a_real_corpus`
- `test_an_incomplete_corpus_declaration_is_refused`
- `test_more_observations_narrow_the_interval`
- `test_the_eval_report_carries_the_verdict_and_the_interval`
- `test_the_shipped_fixture_run_is_not_admissible`

## `apps/api/tests/test_tevv_attestation_boundary.py`

- SHA-256: `cbb5099fb3ad0a7b549bfe4e2d0b7abed181b6765997d691e769ff707761b5c5`
- Lines: 142
- Tests: 8
- KORPUS imports: `korpus.application.provenance`

Test predicates:
- `test_pretrusted_signed_production_like_tevv_evidence_can_clear_environment_boundary`
- `test_production_like_string_without_trusted_attestation_does_not_pass_tevv_gate`
- `test_trusted_aggregate_only_tevv_summary_cannot_replace_case_ledger`
- `test_trusted_tevv_duplicate_observation_ids_fail_closed`
- `test_trusted_tevv_ledger_must_cover_required_attack_families`
- `test_trusted_tevv_summary_cannot_hide_ledger_leakage_failure`
- `test_trusted_tevv_summary_cannot_hide_null_false_accept`
- `test_trusted_tevv_wrong_evidence_schema_fails_closed`

## `apps/api/tests/test_tevv_ledger_boundary.py`

- SHA-256: `066a1666f033b6b9c253d08ee1a45eb5f17dc9c20b53404db1533b9416dd40ea`
- Lines: 97
- Tests: 7
- KORPUS imports: `korpus.application.tevv_evidence`

Test predicates:
- `test_duplicate_observation_ids_fail_closed`
- `test_failure_counts_come_from_rows_not_top_level_claims`
- `test_malformed_row_does_not_count_toward_observation_floor`
- `test_missing_attack_family_cannot_be_repaired_by_declared_summary`
- `test_null_false_accepts_are_recomputed_from_null_ledger`
- `test_signed_summary_counters_without_observation_ledger_are_not_evidence`
- `test_tevv_aggregates_are_recomputed_from_case_ledgers`

## `apps/api/tests/test_token_issuance_refusals.py`

- SHA-256: `a94f8a19545bdc15ae3a7531f6abb41800228316224e94762795385c0e1dd5b3`
- Lines: 94
- Tests: 5
- KORPUS imports: `korpus.config`, `korpus.domain.models`, `korpus.security.auth`

Test predicates:
- `test_a_lifetime_outside_the_configured_bound_is_refused`
- `test_a_token_issued_in_jwt_mode_carries_the_identity`
- `test_local_issuance_is_unavailable_in_oidc_mode`
- `test_local_issuance_is_unavailable_when_authentication_is_disabled`
- `test_the_bound_is_the_configured_one_rather_than_a_constant`

## `apps/api/tests/test_tuning.py`

- SHA-256: `26b8f47b53e2898404f16b164039a419afdd44bcabeb87d4975e76185091bff8`
- Lines: 43
- Tests: 2
- KORPUS imports: `korpus.application.retrieval`, `korpus.application.tuning`

Test predicates:
- `test_ranking_metrics_are_bounded_and_exact_target_is_first`
- `test_tuner_is_deterministic_and_returns_convex_weights`

## `apps/api/tests/test_undated_source_limitation.py`

- SHA-256: `ab7c906f5ad25bb0c5ba7911bd9cffc061521c1f879285a621ea7e4394dea5d1`
- Lines: 78
- Tests: 3
- KORPUS imports: none

Test predicates:
- `test_a_citation_without_a_publication_date_says_so`
- `test_a_dated_source_carries_no_such_notice`
- `test_the_notice_counts_citations_not_versions`

## `apps/api/tests/test_undecodable_text_refusal.py`

- SHA-256: `55de2cd2338e28e5f066569cd17c5d751af025240e27043241f0c21d84a9f0c8`
- Lines: 62
- Tests: 4
- KORPUS imports: `korpus.infrastructure.extraction`

Test predicates:
- `test_a_lone_surrogate_is_refused_by_name`
- `test_the_refusal_names_the_text_not_the_record`
- `test_the_undecodable_text_is_not_silently_repaired`
- `test_valid_text_still_passes`

## `apps/api/tests/test_v5_security_kernel.py`

- SHA-256: `43ead08025675b62f89696a66ac16add5a526e5cbfc639eb79f820c765459895`
- Lines: 625
- Tests: 20
- KORPUS imports: `korpus.application.calibration`, `korpus.application.evidence`, `korpus.application.ingestion`, `korpus.application.policy`, `korpus.application.retrieval`, `korpus.composition`, `korpus.domain.models`, `korpus.infrastructure.extraction`, `korpus.infrastructure.object_store`, `korpus.infrastructure.repository`, `korpus.security.entitlements`, `korpus.security.oidc`, `korpus.security.scanning`, `korpus.security.source_authenticity`

Test predicates:
- `test_a_new_version_of_an_existing_document_is_scanned_too`
- `test_authority_priors_are_profile_inputs_not_hidden_constants`
- `test_clamd_fails_closed_on_empty_or_unexpected_response`
- `test_clamd_instream_protocol_and_detection`
- `test_compartment_noninterference_is_enforced_before_retrieval`
- `test_contradiction_gate_detects_negation_and_numeric_conflicts`
- `test_detached_source_signature_binds_content_and_metadata`
- `test_entitlement_profile_digest_and_deny_list_are_fail_closed`
- `test_entitlement_projection_ignores_privileged_token_claims`
- `test_html_extraction_drops_script_style_and_preserves_text`
- `test_ingestion_stops_before_parser_when_malware_scanner_rejects`
- `test_injection_detector_does_not_block_benign_normative_language`
- `test_injection_detector_handles_zero_width_homoglyphs_and_role_markers`
- `test_oidc_assurance_requires_acr_mfa_and_recent_authentication`
- `test_parser_sandbox_setting_selects_isolated_parser`
- `test_sentence_segmenter_preserves_offsets_for_decimals_abbreviations_and_lists`
- `test_the_extraction_adapter_runs_the_isolated_parser_when_told_to`
- `test_the_sandbox_setting_off_reaches_the_port_as_false`
- `test_type_verification_rejects_pdf_extension_with_non_pdf_content`
- `test_ukrainian_morphology_and_temporal_relevance_are_explicit`

## `apps/api/tests/test_validity_boundaries.py`

- SHA-256: `a275d3d2de0862fab08f9c6d5a9159b4404715cc428447f420a5076de56bbd24`
- Lines: 247
- Tests: 9
- KORPUS imports: `korpus.domain.models`, `korpus.infrastructure.repository`

Test predicates:
- `test_a_rescinded_version_stops_governing_on_the_day_of_rescission`
- `test_a_version_still_governs_on_the_last_day_it_names`
- `test_a_version_takes_effect_on_the_day_it_names`
- `test_rescission_removes_the_document_from_search_on_its_own_day`
- `test_sql_and_domain_agree_on_every_day_around_both_bounds`
- `test_the_candidate_query_alone_excludes_an_invalid_version`
- `test_the_closed_interval_holds_at_both_ends`
- `test_the_search_path_keeps_a_document_on_the_last_day_it_names`
- `test_the_search_path_withholds_a_document_before_it_takes_effect`

## `apps/api/tests/test_versioning.py`

- SHA-256: `c594bb559037a52c7c21bf7f4254e64cc0b664e2ee7a3268846b90853d893a46`
- Lines: 125
- Tests: 4
- KORPUS imports: `korpus.domain.models`, `korpus.infrastructure.repository`

Test predicates:
- `test_competing_branch_cannot_be_approved`
- `test_new_approved_version_supersedes_old_version_in_current_retrieval`
- `test_optimistic_state_transition_kills_double_approval`
- `test_supersedes_must_reference_same_document`

## `apps/api/tests/test_web_score_presentation.py`

- SHA-256: `43048ce6dd6187d68e3e7ed540b53b49fd058011e5c04478ff3245b0bd0103f3`
- Lines: 42
- Tests: 3
- KORPUS imports: none

Test predicates:
- `test_the_score_is_labelled_as_a_ranking_utility_not_a_confidence`
- `test_the_ui_states_that_the_score_is_not_a_probability`
- `test_the_web_validator_enforces_the_disclaimer`

