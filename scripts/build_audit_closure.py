#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.evidence_registry import (  # noqa: E402  (path set above)
    verify_closure_registry,
)

SOURCE = ROOT / "docs/audit/source/KORPUS_v4_FINDINGS_REGISTER_2026-08-01.json"
OUT_DIR = ROOT / "docs/audit/closure"

# Reclassified 2026-08-05. Each move carries a test that fails without the fix and a
# mutant that removes it and dies; a status changed without both is a claim.
CLOSED_LOCAL = {
    "IAM-001", "IAM-003", "IAM-004",
    "ING-001", "ING-002", "ING-003", "ING-004", "ING-005",
    "ING-006", "ING-007", "ING-010", "ING-011",
    "RAG-002", "RAG-004", "RAG-006", "RAG-008", "RAG-019",
    "SUP-004", "COD-010", "OPS-002",
    # 2026-08-05: lock files carry sha256 for all 68 artefacts and every install site
    # passes --require-hashes; the validator's complexity is 5 and 57 where it was 102
    # and 103; every broad handler must re-raise, degrade or record; every image in the
    # pipeline, the compose file and both Dockerfiles is pinned by digest.
    "SUP-002", "COD-002", "COD-003", "SUP-001",
}

MITIGATED_LOCAL = {
    "GOV-002", "GOV-003", "GOV-005",
    "IAM-002", "IAM-005", "IAM-006", "IAM-007",
    "ING-008", "ING-009",
    "RAG-005", "RAG-007", "RAG-010", "RAG-011", "RAG-012", "RAG-015", "RAG-018", "RAG-020",
    "INF-002", "INF-007", "INF-010",
    "SRE-003", "SRE-006",
    "SUP-006",
    "COD-005", "COD-006", "COD-007", "COD-008", "COD-009",
    "AUD-001", "AUD-002",
    "DATA-001", "DATA-002", "DATA-004",
    # 2026-08-05: a material local control now exists; the residue is external or
    # partial, and named as such in TECHNICAL_DEBT_V5.md rather than counted as closed.
    "RAG-009",   # rules carry examples and the unknown class fails closed; a trained
                 # classifier on a blind set with per-class metrics remains
    "RAG-013",   # numbers, units and tables detected; formula structure remains
    "RAG-017",   # embedding drift has four states; online answer-quality does not
    "INF-009",   # telemetry reports REQUESTED_NOT_ACTIVE; a durable backend is external
    "SUP-009",   # 68/68 licenses read from metadata; legal review is external
    "COD-004",   # branch coverage 0.7726 against policy, checked where it is produced
    "AUD-004",   # export is resumable and gap-evident; the SIEM itself is external
}

EXTERNAL_DEBT = {
    "GOV-001", "GOV-004", "GOV-006",
    "IAM-008",
    "ING-012",
    "RAG-001", "RAG-003", "RAG-014",
    "INF-001", "INF-003", "INF-004", "INF-005", "INF-006", "INF-008", "INF-011", "INF-012",
    "SRE-001", "SRE-002", "SRE-004", "SRE-005", "SRE-007",
    "SUP-003", "SUP-005", "SUP-007", "SUP-008",
    "WEB-002", "AUD-003", "DATA-003",
    "OPS-001", "OPS-003", "OPS-005",
}

OPEN_TECH_DEBT = {
    "RAG-016",
    "COD-001",
    "WEB-001", "OPS-004",
}

EVIDENCE: dict[str, list[str]] = {
    "GOV-002": [
        "docs/governance/AI_SYSTEM_CARD_V5.md",
        "docs/governance/RISK_REGISTER.md",
        "docs/operations/TEVV_PLAN_V5.md",
    ],
    "GOV-003": [
        "apps/api/src/korpus/security/corpus_governance.py",
        "apps/api/tests/test_corpus_governance.py",
        "docs/governance/DATA_HANDLING_STANDARD_V5.md",
    ],
    "GOV-005": [
        "apps/api/src/korpus/security/reviewers.py",
        "apps/api/migrations/versions/0009_reviewer_credentials.py",
        "apps/api/tests/test_reviewer_registry.py",
    ],
    "IAM-001": ["apps/api/src/korpus/config.py", "apps/api/tests/test_auth.py"],
    "IAM-002": [
        "apps/api/src/korpus/security/browser_oidc.py",
        "apps/api/tests/test_browser_oidc.py",
        "apps/web/public/app.js",
    ],
    "IAM-003": [
        "apps/api/src/korpus/security/entitlements.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_entitlement_projection_ignores_privileged_token_claims",
    ],
    "IAM-004": [
        "apps/api/src/korpus/domain/models.py",
        "apps/api/src/korpus/infrastructure/repository.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_compartment_noninterference_is_enforced_before_retrieval",
    ],
    "IAM-005": [
        "apps/api/src/korpus/security/oidc.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_oidc_assurance_requires_acr_mfa_and_recent_authentication",
    ],
    "IAM-006": [
        "apps/api/migrations/versions/0003_infrastructure_hardening.py",
        "apps/api/tests/test_postgres_integration.py",
        ".gitlab-ci.yml::api:postgres-and-restore",
    ],
    "IAM-007": [
        "apps/api/src/korpus/security/entitlements.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_entitlement_profile_digest_and_deny_list_are_fail_closed",
    ],
    "ING-001": [
        "apps/api/src/korpus/api/routes.py",
        "apps/api/tests/test_infrastructure_hardening.py",
    ],
    "ING-002": [
        "apps/api/src/korpus/application/ingestion_jobs.py",
        "apps/api/src/korpus/infrastructure/ingestion_jobs.py",
        "apps/api/tests/test_durable_ingestion_jobs.py",
    ],
    "ING-003": [
        "apps/api/src/korpus/security/scanning.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_ingestion_stops_before_parser_when_malware_scanner_rejects",
    ],
    "ING-004": [
        "apps/api/src/korpus/infrastructure/parser_worker.py",
        "apps/api/src/korpus/infrastructure/extraction.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_parser_sandbox_setting_selects_isolated_parser",
    ],
    "ING-005": [
        "apps/api/src/korpus/infrastructure/extraction.py",
        "apps/api/tests/test_structured_evidence_and_fuzz.py",
    ],
    "ING-006": [
        "apps/api/src/korpus/infrastructure/extraction.py",
        "apps/api/tests/test_extraction.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_type_verification_rejects_pdf_extension_with_non_pdf_content",
    ],
    "ING-007": [
        "apps/api/src/korpus/infrastructure/extraction.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_html_extraction_drops_script_style_and_preserves_text",
    ],
    "ING-008": [
        "apps/api/src/korpus/application/ingestion_jobs.py",
        "apps/api/tests/test_durable_ingestion_jobs.py"
        "::test_object_inventory_reconciliation_detects_missing_and_orphaned_files",
    ],
    "ING-009": [
        "apps/api/src/korpus/application/extraction_quality.py",
        "apps/api/migrations/versions/0008_extraction_quality_governance.py",
        "apps/api/tests/test_extraction_quality_governance.py",
    ],
    "ING-010": [
        "apps/api/src/korpus/security/source_authenticity.py",
        "apps/api/migrations/versions/0006_source_authenticity.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_detached_source_signature_binds_content_and_metadata",
    ],
    "ING-011": [
        "apps/api/src/korpus/application/fingerprints.py",
        "apps/api/migrations/versions/0007_near_duplicate_governance.py",
        "apps/api/tests/test_near_duplicate_governance.py",
    ],
    "RAG-002": [
        "apps/api/src/korpus/application/calibration.py",
        "apps/api/tests/test_calibration.py"
        "::test_calibration_profile_and_bound_artifacts_reject_tampering",
    ],
    "RAG-004": [
        "apps/api/src/korpus/application/answer_query.py",
        "apps/api/tests/test_answers.py"
        "::test_approved_document_produces_exact_claim_bound_citation",
    ],
    "RAG-005": [
        "apps/api/src/korpus/application/evidence.py",
        "apps/api/src/korpus/application/answer_query.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_contradiction_gate_detects_negation_and_numeric_conflicts",
    ],
    "RAG-006": [
        "apps/api/src/korpus/application/answer_query.py",
        "apps/api/tests/test_structured_evidence_and_fuzz.py",
    ],
    "RAG-007": [
        "apps/api/src/korpus/application/calibration.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_authority_priors_are_profile_inputs_not_hidden_constants",
    ],
    "RAG-008": [
        "apps/api/src/korpus/application/retrieval.py",
        "apps/api/tests/test_versioning.py",
    ],
    "RAG-010": [
        "apps/api/src/korpus/application/evidence.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_injection_detector_handles_zero_width_homoglyphs_and_role_markers",
    ],
    "RAG-011": [
        "apps/api/src/korpus/application/evidence.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_sentence_segmenter_preserves_offsets_for_decimals_abbreviations_and_lists",
    ],
    "RAG-012": [
        "apps/api/src/korpus/application/retrieval.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_ukrainian_morphology_and_temporal_relevance_are_explicit",
    ],
    "RAG-015": [
        "apps/api/src/korpus/security/corpus_governance.py",
        "apps/api/src/korpus/infrastructure/semantic.py",
        "apps/api/tests/test_corpus_governance.py",
    ],
    "RAG-018": [
        "apps/api/src/korpus/security/source_authenticity.py",
        "apps/api/src/korpus/security/reviewers.py",
        "apps/api/src/korpus/application/fingerprints.py",
    ],
    "RAG-019": [
        "apps/web/public/index.html",
        "apps/web/public/app.js",
        "apps/web/scripts/validate.mjs",
        "apps/api/tests/test_web_score_presentation.py"
        "::test_the_ui_states_that_the_score_is_not_a_probability",
        ".gitlab-ci.yml::web:test",
    ],
    "RAG-020": ["apps/api/src/korpus/application/calibration.py", "evals/EVALUATION_PROTOCOL.md"],
    "INF-002": ["deploy/kubernetes", "scripts/validate_kubernetes.py"],
    "INF-007": ["deploy/kubernetes/base/networkpolicies.yaml", "docker-compose.yml"],
    "INF-010": [
        "apps/api/src/korpus/infrastructure/audit_anchor.py",
        "apps/api/tests/test_http_audit_anchor.py",
    ],
    "SRE-003": ["apps/api/src/korpus/infrastructure/observability.py", "infra/otel-collector.yaml"],
    "SRE-006": ["apps/api/src/korpus/main.py", "docs/operations/SLO_AND_RELEASE_POLICY_V5.md"],
    "SUP-004": [".gitlab-ci.yml::container:build"],
    "SUP-006": [
        ".gitlab-ci.yml",
        "scripts/run_mutation_tests.py",
        "scripts/validate_infrastructure.py",
    ],
    "COD-005": ["scripts/run_mutation_tests.py", "var/mutation-report.json"],
    "SUP-001": [
        "docker-compose.yml",
        "apps/api/Dockerfile",
        "apps/web/Dockerfile",
        "apps/api/tests/test_image_pinning.py::test_a_tag_without_a_digest_is_refused",
        "apps/api/tests/test_gate_parity.py::test_every_ci_image_pins_an_exact_tag",
    ],
    "SUP-002": [
        "apps/api/requirements.runtime.lock",
        "apps/api/requirements.dev.lock",
        "apps/api/tests/test_gate_parity.py::test_every_pinned_dependency_carries_a_hash",
        "apps/api/tests/test_gate_parity.py"
        "::test_every_install_of_a_lock_file_requires_those_hashes",
    ],
    "COD-002": [
        "apps/api/src/korpus/controlled_requirements.py",
        "apps/api/src/korpus/infrastructure_requirements.py",
        "apps/api/tests/test_controlled_configuration_refusals.py",
        "apps/api/tests/test_requirement_registry.py",
        "config/operations/module-budget.json",
    ],
    "COD-003": [
        "apps/api/tests/test_exception_handling_discipline.py"
        "::test_no_broad_handler_turns_a_fault_into_evidence_of_health",
        "apps/api/tests/test_exception_handling_discipline.py"
        "::test_no_bare_except_hides_which_failure_occurred",
    ],
    "COD-004": [
        "scripts/check_coverage_thresholds.py",
        "apps/api/tests/test_gate_parity.py"
        "::test_the_coverage_thresholds_are_checked_where_coverage_is_produced",
    ],
    "RAG-009": [
        "apps/api/src/korpus/application/risk_rules.py",
        "apps/api/tests/test_risk_rules.py"
        "::test_an_unrecognised_query_is_unclassified_not_standard",
        "apps/api/tests/test_risk_rules.py"
        "::test_a_rephrased_operational_question_is_still_operational",
        "apps/api/tests/test_risk_rules.py::test_unclassified_costs_more_than_standard",
    ],
    "RAG-013": [
        "apps/api/src/korpus/application/numeric_integrity.py",
        "apps/api/src/korpus/application/table_integrity.py",
        "apps/api/tests/test_numeric_integrity.py",
        "apps/api/tests/test_table_integrity.py",
    ],
    "RAG-017": [
        "apps/api/src/korpus/application/embedding_coverage.py",
        "apps/api/tests/test_embedding_coverage.py",
    ],
    "INF-009": [
        "apps/api/src/korpus/infrastructure/observability.py",
        "apps/api/tests/test_telemetry_status.py",
    ],
    "SUP-009": [
        "scripts/generate_supply_chain_inventory.py",
        "apps/api/tests/test_gate_parity.py"
        "::test_scripts_reading_installed_metadata_run_under_the_locked_interpreter",
    ],
    "AUD-004": [
        "apps/api/src/korpus/application/audit_export.py",
        "scripts/export_audit.py",
        "apps/api/tests/test_audit_export.py",
        "apps/api/src/korpus/application/retention.py",
    ],
    "COD-006": [
        "apps/api/tests/test_structured_evidence_and_fuzz.py",
        "apps/api/tests/test_v5_security_kernel.py"
        "::test_parser_sandbox_setting_selects_isolated_parser",
    ],
    "COD-007": ["apps/api/pyproject.toml", ".gitlab-ci.yml::api:quality"],
    "COD-008": [
        "apps/web/scripts/validate.mjs",
        "apps/web/package.json",
        "apps/api/tests/test_browser_oidc.py",
    ],
    "COD-009": ["pytest.ini", ".gitlab-ci.yml::api:test"],
    "COD-010": [
        "contracts/openapi.json",
        "scripts/openapi_contract.py",
        "apps/api/tests/test_api_contract.py",
    ],
    "AUD-001": [
        "apps/api/src/korpus/infrastructure/repository.py",
        "docs/security/KEY_AND_BREAK_GLASS_V5.md",
    ],
    "AUD-002": [
        "apps/api/src/korpus/infrastructure/audit_anchor.py",
        "apps/api/tests/test_http_audit_anchor.py",
    ],
    "DATA-001": [
        "apps/api/src/korpus/security/corpus_governance.py",
        "apps/api/tests/test_corpus_governance.py",
        "docs/governance/DATA_HANDLING_STANDARD_V5.md",
    ],
    "DATA-002": [
        "docs/governance/DATA_HANDLING_STANDARD_V5.md",
        "apps/api/src/korpus/security/corpus_governance.py",
    ],
    "DATA-004": [
        "apps/api/src/korpus/cli.py",
        "apps/api/tests/test_durable_ingestion_jobs.py"
        "::test_object_inventory_reconciliation_detects_missing_and_orphaned_files",
    ],
    "OPS-002": [
        ".gitlab-ci.yml",
        "apps/api/tests/test_gate_parity.py::test_ci_does_not_retry_failing_jobs",
    ],
}


def status_for(finding_id: str) -> str:
    memberships = [
        name
        for name, values in (
            ("CLOSED_LOCAL", CLOSED_LOCAL),
            ("MITIGATED_LOCAL", MITIGATED_LOCAL),
            ("EXTERNAL_DEBT", EXTERNAL_DEBT),
            ("OPEN_TECH_DEBT", OPEN_TECH_DEBT),
        )
        if finding_id in values
    ]
    if len(memberships) != 1:
        raise RuntimeError(
            f"finding {finding_id} has invalid closure classification: {memberships}"
        )
    return memberships[0]


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    findings = source["findings"]
    source_ids = {item["id"] for item in findings}
    classified = CLOSED_LOCAL | MITIGATED_LOCAL | EXTERNAL_DEBT | OPEN_TECH_DEBT
    if source_ids != classified:
        raise RuntimeError(
            f"closure map mismatch missing={sorted(source_ids-classified)} "
            f"extra={sorted(classified-source_ids)}"
        )

    # Counting evidence entries proved nothing: the registry named files without
    # anyone opening them (destruction stage 2026-08-03). Every citation is now
    # resolved, and a CLOSED finding must cite a test that exists.
    statuses = {item["id"]: status_for(item["id"]) for item in findings}
    unresolved = verify_closure_registry(ROOT, EVIDENCE, statuses)
    if unresolved:
        raise RuntimeError(
            "the closure registry cites evidence that does not resolve:\n  "
            + "\n  ".join(unresolved)
        )

    output = []
    for item in findings:
        status = statuses[item["id"]]
        evidence = EVIDENCE.get(item["id"], [])
        if status in {"CLOSED_LOCAL", "MITIGATED_LOCAL"} and not evidence:
            raise RuntimeError(f"local status lacks evidence: {item['id']}")
        output.append(
            {
                **item,
                "v5_status": status,
                "v5_evidence": evidence,
                "v5_remaining_acceptance": (
                    "None inside the frozen local scope; external acceptance may still apply."
                    if status == "CLOSED_LOCAL"
                    else item["acceptance_predicate"]
                ),
            }
        )

    counts = Counter(item["v5_status"] for item in output)
    severity = Counter(item["severity"] for item in output if item["v5_status"] != "CLOSED_LOCAL")
    report = {
        "schema": "korpus-audit-closure-v5",
        "source_release": source["release"],
        "target_release": "v5.0.0",
        "scope_claim": (
            "Complete classification of all 99 v4 findings. CLOSED_LOCAL means the encoded "
            "local predicate has executable evidence; it is not production authorization."
        ),
        "counts": dict(sorted(counts.items())),
        "remaining_by_severity": dict(sorted(severity.items())),
        "findings": output,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "KORPUS_v5_FINDINGS_CLOSURE.json"
    csv_path = OUT_DIR / "KORPUS_v5_FINDINGS_CLOSURE.csv"
    md_path = OUT_DIR / "KORPUS_v5_CLOSURE_SUMMARY.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = [
        "id", "domain", "severity", "state", "title", "v5_status", "v5_evidence",
        "impact", "required_action", "tools_methods", "acceptance_predicate",
        "v5_remaining_acceptance",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for item in output:
            row = {key: item.get(key, "") for key in columns}
            row["v5_evidence"] = " | ".join(item["v5_evidence"])
            writer.writerow(row)
    lines = [
        "# KORPUS v5 audit closure summary",
        "",
        "This register classifies all 99 v4 findings without converting missing external "
        "evidence into PASS.",
        "",
        "| Status | Count | Meaning |",
        "|---|---:|---|",
    ]
    meanings = {
        "CLOSED_LOCAL": "Executable local acceptance predicate passed.",
        "MITIGATED_LOCAL": (
            "Material control exists; live, corpus, or independent acceptance remains."
        ),
        "EXTERNAL_DEBT": "Cannot be closed inside this repository/session.",
        "OPEN_TECH_DEBT": "Engineering implementation remains open.",
    }
    for key in ("CLOSED_LOCAL", "MITIGATED_LOCAL", "EXTERNAL_DEBT", "OPEN_TECH_DEBT"):
        lines.append(f"| {key} | {counts[key]} | {meanings[key]} |")
    lines += ["", "## Remaining blockers", ""]
    for item in output:
        if item["v5_status"] != "CLOSED_LOCAL":
            lines.append(
                f"- **{item['id']} · {item['severity']} · {item['v5_status']}** — {item['title']}"
            )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        "findings": len(output),
        "counts": dict(counts),
        "remaining_by_severity": dict(severity),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
