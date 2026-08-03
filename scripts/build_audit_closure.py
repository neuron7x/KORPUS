#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/audit/source/KORPUS_v4_FINDINGS_REGISTER_2026-08-01.json"
OUT_DIR = ROOT / "docs/audit/closure"

CLOSED_LOCAL = {
    "IAM-001", "IAM-003", "IAM-004",
    "ING-001", "ING-002", "ING-003", "ING-004", "ING-005",
    "ING-006", "ING-007", "ING-010", "ING-011",
    "RAG-002", "RAG-004", "RAG-006", "RAG-008", "RAG-019",
    "SUP-004", "COD-010", "OPS-002",
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
    "RAG-009", "RAG-013", "RAG-016", "RAG-017",
    "INF-009",
    "SUP-001", "SUP-002", "SUP-009",
    "COD-001", "COD-002", "COD-003", "COD-004",
    "WEB-001", "AUD-004", "OPS-004",
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
        "korpus CLI reconcile-objects",
        "apps/api/tests/test_durable_ingestion_jobs.py"
        "::test_object_inventory_reconciliation_detects_missing_and_orphaned_files",
    ],
    "OPS-002": [".gitlab-ci.yml::default.retry=0"],
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

    output = []
    for item in findings:
        status = status_for(item["id"])
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
