"""Supply-chain admission predicates for GCP production delivery."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the group modules are imported *by* production_contract, not before it
    from scripts.gcp.production_contract import Sources


def evaluate(s: Sources) -> list[tuple[str, bool, str]]:
    workflow = s.production_workflow
    return [
        (
            "AUTOMATIC_TRAFFIC_ROLLBACK",
            "name: Capture serving revisions for rollback" in workflow
            and "python scripts/gcp/traffic_snapshot.py" in workflow
            and "name: Roll back Cloud Run traffic on failed promotion" in workflow
            and "if: failure()" in workflow
            and "python scripts/gcp/rollback_traffic.py" in workflow
            and '--api-spec "${PREVIOUS_API_TRAFFIC}"' in workflow
            and '--web-spec "${PREVIOUS_WEB_TRAFFIC}"' in workflow
            and "--output-dir reports/production" in workflow,
            "pre-deploy revision-exact traffic allocation is captured and restored automatically after a failed promotion",
        ),
        (
            "PROVENANCE_ADMISSION_ENFORCED",
            workflow.count("push-to-registry: true") == 2
            and "name: Enforce build provenance admission" in workflow
            and 'gh attestation verify "oci://${ref}"' in workflow
            and "--bundle-from-oci" in workflow
            and '--repo "${GITHUB_REPOSITORY}"' in workflow
            and '--signer-workflow "${signer_workflow}"' in workflow
            and '--source-ref "refs/heads/main"' in workflow
            and '--source-digest "${GITHUB_SHA}"' in workflow
            and "--deny-self-hosted-runners" in workflow,
            "API/web deployment is admitted only after OCI-hosted SLSA provenance verifies against exact repository, workflow, main ref and commit on a GitHub-hosted runner",
        ),
    ]
