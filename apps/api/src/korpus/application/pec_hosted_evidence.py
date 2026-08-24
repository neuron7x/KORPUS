from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .pec_audit_trace import extract_audit_trace
from .pec_canary_admission import evaluate_canary
from .pec_human_judgment import evaluate_human_judgments
from .pec_revision_binding import RevisionBinding
from .pec_training_lineage import validate_training_lineage
from .production_assurance import gate_payload


@dataclass(frozen=True)
class HostedEvidenceVerdict:
    valid: bool
    failures: tuple[str, ...]


def validate_hosted_evidence(
    receipt: Mapping[str, object], *, release: str, source_digest: str
) -> HostedEvidenceVerdict:
    checks = {
        "provider": str(receipt.get("provider", "")) in {"github-actions", "gitlab-ci"},
        "run_id": bool(str(receipt.get("run_id", "")).strip()),
        "workflow": bool(str(receipt.get("workflow", "")).strip()),
        "release": str(receipt.get("release", "")) == release,
        "source_digest": str(receipt.get("source_digest", "")) == source_digest,
        "not_local_self_attested": receipt.get("local_self_attested") is not True,
    }
    failures = tuple(name for name, ok in checks.items() if not ok)
    return HostedEvidenceVerdict(not failures, failures)


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _binding(evidence: Mapping[str, object], release: str) -> tuple[RevisionBinding | None, list[str]]:
    raw = _mapping(evidence.get("binding"))
    if raw is None:
        return None, ["binding:missing"]
    try:
        return RevisionBinding.from_mapping(raw, expected_release=release), []
    except ValueError as error:
        return None, [f"binding:{error}"]


def _audit(
    evidence: Mapping[str, object], binding: RevisionBinding | None
) -> tuple[bool, str, list[str]]:
    rows = evidence.get("audit_rows")
    if binding is None or not isinstance(rows, list):
        return False, "", ["audit_trace:missing"]
    try:
        trace = extract_audit_trace(rows, binding)
    except (TypeError, ValueError) as error:
        return False, "", [f"audit_trace:{error}"]
    if not trace.event_ids:
        return False, trace.sha256, ["audit_trace:empty"]
    return True, trace.sha256, []


def _training(
    evidence: Mapping[str, object], binding: RevisionBinding | None
) -> tuple[bool, list[str]]:
    receipt = _mapping(evidence.get("training_receipt"))
    if binding is None or receipt is None:
        return False, ["training_lineage:missing"]
    verdict = validate_training_lineage(
        receipt,
        release=binding.release,
        profile=binding.profile,
        source_revision=binding.revision,
        dataset_sha256=str(evidence.get("training_dataset_sha256", "")),
    )
    digest_bound = str(receipt.get("receipt_sha256", "")) == binding.training_receipt_sha256
    failures = [f"training_lineage:{item}" for item in verdict.failures]
    if not digest_bound:
        failures.append("training_lineage:receipt_binding")
    return verdict.valid and digest_bound, failures


def _judgments(
    evidence: Mapping[str, object], binding: RevisionBinding | None
) -> tuple[bool, int, list[str]]:
    expected = evidence.get("expected_case_ids")
    rows = evidence.get("judgments")
    if binding is None or not isinstance(expected, list) or not isinstance(rows, list):
        return False, 0, ["human_judgments:missing"]
    verdict = evaluate_human_judgments(
        rows,
        expected_case_ids=[str(item) for item in expected],
        binding=binding,
    )
    return verdict.admissible, verdict.judgments, [f"human_judgments:{item}" for item in verdict.failures]


def _hosted(
    evidence: Mapping[str, object], *, release: str, source_digest: str
) -> tuple[bool, list[str]]:
    receipt = _mapping(evidence.get("hosted_receipt"))
    if receipt is None:
        return False, ["hosted_evidence:missing"]
    verdict = validate_hosted_evidence(receipt, release=release, source_digest=source_digest)
    return verdict.valid, [f"hosted_evidence:{item}" for item in verdict.failures]


def _authority_gate(
    evidence: Mapping[str, object],
    *,
    release: str,
    source_digest: str,
    attestation_verified: bool,
    trusted_signer: bool,
    signer_fingerprint: str,
) -> tuple[dict[str, Any], RevisionBinding | None, list[str]]:
    binding, failures = _binding(evidence, release)
    audit_ok, trace_sha, audit_failures = _audit(evidence, binding)
    training_ok, training_failures = _training(evidence, binding)
    judgments_ok, judgment_count, judgment_failures = _judgments(evidence, binding)
    hosted_ok, hosted_failures = _hosted(evidence, release=release, source_digest=source_digest)
    failures.extend((*audit_failures, *training_failures, *judgment_failures, *hosted_failures))
    checks = {
        "evidence_schema": evidence.get("schema") == "korpus.pec-production-evidence.v1",
        "source_bound": evidence.get("source_digest") == source_digest,
        "binding_valid": binding is not None,
        "audit_trace_nonempty": audit_ok,
        "training_lineage": training_ok,
        "human_judgments": judgments_ok,
        "hosted_evidence": hosted_ok,
        "attestation_verified": attestation_verified,
        "trusted_signer": trusted_signer,
    }
    check_failures = [name for name, ok in checks.items() if not ok]
    gate = gate_payload(
        "pec_authority",
        status="PASS" if not check_failures else "FAIL",
        source_digest=source_digest,
        release=release,
        checks=checks,
        failures=check_failures,
        environment_class=binding.environment_class if binding else None,
        revision=binding.revision if binding else None,
        profile=binding.profile if binding else None,
        phase=binding.phase if binding else None,
        audit_trace_sha256=trace_sha,
        human_judgments=judgment_count,
        assessor_signer_fingerprint=signer_fingerprint,
    )
    return gate, binding, failures


def _canary_gate(
    evidence: Mapping[str, object],
    *,
    authority: Mapping[str, object],
    binding: RevisionBinding | None,
    release: str,
    source_digest: str,
) -> dict[str, Any]:
    receipt = _mapping(evidence.get("canary"))
    revision = str(evidence.get("cloud_run_revision", ""))
    canary = None
    if binding is not None and receipt is not None and revision:
        minimum_samples = evidence.get("minimum_canary_samples", 100)
        maximum_server_error_rate = evidence.get("maximum_server_error_rate", 0.01)
        try:
            canary = evaluate_canary(
                receipt,
                binding=binding,
                cloud_run_revision=revision,
                minimum_samples=minimum_samples,  # type: ignore[arg-type]
                maximum_server_error_rate=maximum_server_error_rate,  # type: ignore[arg-type]
            )
        except ValueError:
            canary = None
    canary_failures = set(canary.failures) if canary is not None else set()
    checks = {
        "authority_pass": authority.get("status") == "PASS",
        "source_bound": evidence.get("source_digest") == source_digest,
        "release_bound": binding is not None and binding.release == release,
        "exact_cloud_run_revision": canary is not None and "cloud_run_revision_mismatch" not in canary_failures,
        "minimum_samples": canary is not None and "insufficient_samples" not in canary_failures,
        "server_error_rate": canary is not None and "server_error_rate" not in canary_failures,
        "human_judgment_admissible": canary is not None and "human_judgment_not_admissible" not in canary_failures,
    }
    failures = [name for name, ok in checks.items() if not ok]
    return gate_payload(
        "pec_canary",
        status="PASS" if not failures else "FAIL",
        source_digest=source_digest,
        release=release,
        checks=checks,
        failures=failures,
        environment_class=binding.environment_class if binding else None,
        cloud_run_revision=revision,
    )


def evaluate_pec_production_evidence(
    evidence: Mapping[str, object],
    *,
    release: str,
    source_digest: str,
    attestation_verified: bool,
    trusted_signer: bool,
    signer_fingerprint: str = "",
) -> dict[str, object]:
    authority, binding, failures = _authority_gate(
        evidence,
        release=release,
        source_digest=source_digest,
        attestation_verified=attestation_verified,
        trusted_signer=trusted_signer,
        signer_fingerprint=signer_fingerprint,
    )
    canary = _canary_gate(
        evidence,
        authority=authority,
        binding=binding,
        release=release,
        source_digest=source_digest,
    )
    return {
        "status": "PASS" if authority["status"] == canary["status"] == "PASS" else "FAIL",
        "authority": authority,
        "canary": canary,
        "diagnostics": failures,
    }
