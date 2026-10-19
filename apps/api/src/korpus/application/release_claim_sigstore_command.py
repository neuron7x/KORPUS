from __future__ import annotations

from korpus.application.release_claim_hosted import SIGNER_WORKFLOW, TRUSTED_ROOT_PATH


def sigstore_command(
    executable: str,
    attestation_path: str,
    bundle_path: str,
    commit: str,
    source_ref: str,
) -> list[str]:
    return [
        executable,
        "attestation",
        "verify",
        attestation_path,
        "--bundle",
        bundle_path,
        "--custom-trusted-root",
        TRUSTED_ROOT_PATH,
        "--repo",
        "neuron7x/KORPUS",
        "--signer-workflow",
        SIGNER_WORKFLOW,
        "--signer-digest",
        commit,
        "--source-digest",
        commit,
        "--source-ref",
        source_ref,
        "--cert-oidc-issuer",
        "https://token.actions.githubusercontent.com",
        "--predicate-type",
        "https://slsa.dev/provenance/v1",
        "--deny-self-hosted-runners",
        "--format",
        "json",
    ]
