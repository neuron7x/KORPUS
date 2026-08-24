"""Runtime admission policy for Predictive Evidence Control artifacts."""
from __future__ import annotations

from typing import Any

from korpus.application.controller_profile import ControllerProfile


def validate_pec_settings(settings: Any, *, controlled: bool) -> None:
    if not settings.pec_enabled:
        if settings.pec_profile_sha256 and settings.pec_profile_path is None:
            raise ValueError("PEC profile digest is configured without a profile path")
        if settings.contextual_retrieval_enabled and controlled:
            raise ValueError("controlled contextual retrieval requires PEC governance")
        return
    required = {
        "profile": settings.pec_profile_path,
        "dataset": settings.pec_dataset_path,
        "system manifest": settings.pec_system_manifest_path,
        "evaluation protocol": settings.pec_evaluation_protocol_path,
        "replay receipt": settings.pec_replay_receipt_path,
    }
    missing = [name for name, path in required.items() if path is None or not path.is_file()]
    if missing:
        raise ValueError(f"PEC artifacts are missing: {', '.join(missing)}")
    if not settings.pec_profile_sha256:
        raise ValueError("PEC controller profile digest is required")
    if controlled and settings.answer_policy_mode != "calibrated":
        raise ValueError("controlled PEC requires the independently calibrated answer policy")
    profile = ControllerProfile.load(
        settings.pec_profile_path, expected_sha256=settings.pec_profile_sha256
    )
    profile.validate_artifact_bindings(
        dataset=settings.pec_dataset_path,
        system_manifest=settings.pec_system_manifest_path,
        evaluation_protocol=settings.pec_evaluation_protocol_path,
        replay_receipt=settings.pec_replay_receipt_path,
    )
    if profile.admission_status != "PASS":
        raise ValueError("PEC controller profile is not admitted")
