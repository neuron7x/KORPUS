"""Terraform admission predicates for GCP production delivery."""

from __future__ import annotations


def evaluate(s: object) -> list[tuple[str, bool, str]]:
    workflow = s.production_workflow
    return [
        (
            "TERRAFORM_STRUCTURAL_ADMISSION",
            "python scripts/gcp/validate_terraform_structure.py --output reports/TERRAFORM_STRUCTURE.json"
            in workflow
            and workflow.find("Validate Terraform structural invariants offline")
            < workflow.find("Install signature-verified Terraform"),
            "offline HCL structure gate runs before signature-verified provider-schema validation",
        )
    ]
