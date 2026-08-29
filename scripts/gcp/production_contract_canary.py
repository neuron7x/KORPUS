"""Fail-closed staged-promotion predicates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the group modules are imported *by* production_contract, not before it
    from scripts.gcp.production_contract import Sources


def evaluate(s: Sources) -> list[tuple[str, bool, str]]:
    workflow = s.production_workflow
    return [
        (
            "ZERO_TRAFFIC_CANDIDATE",
            s.services.count('tag     = "candidate"') == 2
            and s.services.count("== 0 ? 100 : 0") == 2
            and 'variable "api_stable_traffic"' in s.runtime_vars
            and 'variable "web_stable_traffic"' in s.runtime_vars,
            "existing serving revisions stay pinned while the new latest revision is created at 0% with a candidate tag; first deploy has no predecessor and serves latest",
        ),
        (
            "PRIVATE_EXACT_CANDIDATE_PROBE",
            'resource "google_cloud_run_v2_job" "candidate_probe"' in s.all_tf
            and 'egress = "ALL_TRAFFIC"' in s.all_tf
            and 'command = ["python", "scripts/gcp/probe_candidate.py"]' in s.all_tf
            and "gcloud run jobs execute korpus-candidate-probe" in workflow
            and "python scripts/gcp/candidate_target.py" in workflow,
            "tagged API/web revisions are deterministically probed by a VPC-routed Cloud Run job before traffic promotion",
        ),
        (
            "STAGED_TRAFFIC_PROMOTION",
            "Promote candidate to bounded canary traffic" in workflow
            and '--to-tags "candidate=${CANARY_PERCENT}"' in workflow
            and "Admit candidate by revision metrics" in workflow
            and "scripts/gcp/canary_metrics.py" in workflow
            and "--minimum-samples 20 --maximum-error-rate 0.01" in workflow
            and "Promote verified candidate to 100 percent" in workflow
            and "--to-tags candidate=100" in workflow
            and workflow.find("Execute exact private candidate probe")
            < workflow.find("Promote candidate to bounded canary traffic")
            < workflow.find("Admit candidate by revision metrics")
            < workflow.find("Promote verified candidate to 100 percent"),
            "non-initial releases progress exact private probe -> bounded public canary -> minimum-sample/error-rate revision admission -> full promotion, with existing failure rollback covering every downstream step",
        ),
    ]
