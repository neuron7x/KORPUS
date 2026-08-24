# KORPUS v0.9.7 — Next-Stage External Evidence Contract

Current software hard predicates: **14/14**. External satisfied: **0/14**.

Every imported artifact must bind exact release/source/revision/environment and must use the signer/independence class required by the predicate.

### `external_independent_redteam` — `EXTERNAL_INDEPENDENT_ATTESTED`

Gate: `redteam`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `report_present`
- `attestation_present`
- `attestation_verified`
- `trusted_signer`
- `source_bound`
- `release_bound`
- `independent_class`
- `preregistered`
- `test_cases_structured`
- `required_attack_families_covered`
- `findings_structured`
- `blocking_findings_closed`
- `declared_status_consistent`
- `metadata:status`

### `live_vulnerability_scanners` — `CURRENT_SCANNERS_PLUS_SBOM_ATTESTED`

Gate: `supply_chain`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `security_scanners_executed_clean`
- `security_scanners_current_commit`
- `container_scanners_executed_clean`
- `container_scanners_current_commit`
- `container_sboms_valid`
- `evidence_manifest_bound`
- `evidence_attestation_verified`
- `evidence_trusted_signer`

### `live_postgres_rls` — `REAL_POSTGRESQL`

Gate: `postgres_security`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `target_files_present`
- `grant_contract_static`
- `postgres_runtime_available`
- `postgres_adversarial_suite`
- `metadata:backend`

### `real_domain_corpus_tevv` — `REAL_DOMAIN_CORPUS`

Gate: `tevv`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `evidence_schema`
- `preregistered`
- `source_bound`
- `release_bound`
- `observation_ledger_structured`
- `null_control_ledger_structured`
- `required_attack_families_covered`
- `tevv_admissible`
- `pass_rate`
- `citation_integrity`
- `leakage`
- `determinism`
- `null_controls`
- `null_false_accepts`
- `attack_families`

### `independent_tevv` — `INDEPENDENT_ATTESTED`

Gate: `tevv`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `independent_class`
- `assessor_structured`
- `assessor_attestation_verified`
- `assessor_trusted_signer`

### `production_like_tevv_environment` — `PRODUCTION_LIKE_OR_PRODUCTION_ATTESTED`

Gate: `tevv`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `environment_class`
- `assessor_attestation_verified`
- `assessor_trusted_signer`

### `production_like_load` — `PRODUCTION_LIKE_LOAD`

Gate: `reliability`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `live_load_soak_executed`
- `load_source_bound`
- `load_environment`
- `load_slo_steady_p95`
- `load_slo_cold_start`

### `trusted_load_attestation` — `TRUSTED_LOAD_ATTESTATION`

Gate: `reliability`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `load_attestation_verified`
- `load_trusted_signer`

### `trusted_recovery_attestation` — `TRUSTED_RECOVERY_ATTESTATION`

Gate: `reliability`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `recovery_drill_executed`
- `recovery_source_bound`
- `recovery_environment`
- `recovery_attestation_verified`
- `recovery_trusted_signer`

### `trusted_hosted_builder` — `HOSTED_BUILDER_PROVENANCE`

Gate: `final_release`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `builder_provenance_verified`
- `builder_trusted`
- `builder_attestation_verified`
- `builder_trusted_signer`

### `trusted_release_signing` — `PRETRUSTED_RELEASE_SIGNER`

Gate: `final_release`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `release_manifest_bound`
- `release_attestation_verified`
- `release_trusted_signer`

### `exact_python_3_12_13_environment` — `EXACT_LOCKED_ENVIRONMENT`

Gate: `exact_environment`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `all_locked_components_installed`
- `all_versions_exact`
- `no_unmanaged_distributions`
- `production_python_exact`
- `lock_hashes_present`
- `metadata:status`

### `pec_human_production_authority` — `HOSTED_HUMAN_EXACT_COHORT_ATTESTED`

Gate: `pec_authority`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `evidence_schema`
- `source_bound`
- `binding_valid`
- `audit_trace_nonempty`
- `training_lineage`
- `human_judgments`
- `hosted_evidence`
- `attestation_verified`
- `trusted_signer`
- `metadata:environment_class`

### `pec_canary_revision_admission` — `EXACT_CLOUD_RUN_REVISION_CANARY_ATTESTED`

Gate: `pec_canary`  
Software ready: **yes**  
External satisfied: **no**

Failed checks:
- `authority_pass`
- `source_bound`
- `release_bound`
- `exact_cloud_run_revision`
- `minimum_samples`
- `server_error_rate`
- `human_judgment_admissible`
- `metadata:environment_class`

## Final condition
Production authorization remains false until every mandatory predicate is `production_satisfied=true`.
