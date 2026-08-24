"""Artifact-lineage validation for PEC promotion receipts."""

from __future__ import annotations

from collections.abc import Mapping

from korpus.application.controller_profile import ControllerProfile


def _field_error(
    receipt: Mapping[str, object] | None, name: str, field: str, expected: str
) -> str | None:
    actual = "" if receipt is None else str(receipt.get(field, ""))
    if not actual:
        return f"binding_missing:{name}:{field}"
    if actual != expected:
        return f"binding_mismatch:{name}:{field}"
    return None


def _flat_binding_errors(
    profile: ControllerProfile,
    receipts: Mapping[str, Mapping[str, object]],
    receipt_file_sha256: Mapping[str, str],
    profile_file_sha256: str,
) -> list[str]:
    checks = [
        ("dataset_audit", "dataset_sha256", profile.dataset_sha256),
        ("counterfactual_replay", "dataset_sha256", profile.dataset_sha256),
        ("training", "dataset_sha256", profile.dataset_sha256),
        ("counterfactual_replay", "corpus_release_id", profile.corpus_release_id),
        ("counterfactual_replay", "evaluation_protocol_sha256", profile.evaluation_protocol_sha256),
        ("counterfactual_replay", "answer_calibration_id", profile.answer_calibration_id),
        ("oracle", "replay_sha256", receipt_file_sha256.get("counterfactual_replay", "")),
        ("training", "oracle_sha256", receipt_file_sha256.get("oracle", "")),
        ("controller_verify", "profile_sha256", profile_file_sha256),
    ]
    errors = [
        error
        for name, field, expected in checks
        if (error := _field_error(receipts.get(name), name, field, expected)) is not None
    ]
    if receipt_file_sha256.get("counterfactual_replay", "") != profile.replay_receipt_sha256:
        errors.append("binding_mismatch:profile:replay_receipt_sha256")
    if receipt_file_sha256.get("training", "") != profile.training_receipt_sha256:
        errors.append("binding_mismatch:profile:training_receipt_sha256")
    return errors


def _nested_binding_errors(
    receipt: Mapping[str, object] | None,
    name: str,
    expected: Mapping[str, str],
) -> list[str]:
    binding = receipt.get("binding") if isinstance(receipt, Mapping) else None
    if not isinstance(binding, Mapping):
        return [f"binding_missing:{name}:binding"]
    return [
        error
        for field, value in expected.items()
        if (error := _field_error(binding, name, field, value)) is not None
    ]


def promotion_binding_errors(
    profile: ControllerProfile,
    receipts: Mapping[str, Mapping[str, object]],
    receipt_file_sha256: Mapping[str, str],
    *,
    profile_file_sha256: str,
) -> list[str]:
    """Require all green PEC receipts to belong to one exact artifact lineage."""
    errors = _flat_binding_errors(profile, receipts, receipt_file_sha256, profile_file_sha256)
    errors.extend(
        _nested_binding_errors(
            receipts.get("ablation"),
            "ablation",
            {
                "dataset_sha256": profile.dataset_sha256,
                "corpus_release_id": profile.corpus_release_id,
                "evaluation_protocol_sha256": profile.evaluation_protocol_sha256,
                "answer_calibration_id": profile.answer_calibration_id,
            },
        )
    )
    errors.extend(
        _nested_binding_errors(
            receipts.get("metamorphic"),
            "metamorphic",
            {
                "corpus_release_id": profile.corpus_release_id,
                "evaluation_protocol_sha256": profile.evaluation_protocol_sha256,
                "answer_calibration_id": profile.answer_calibration_id,
            },
        )
    )
    return sorted(set(errors))
