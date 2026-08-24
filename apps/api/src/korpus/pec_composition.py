from __future__ import annotations

from korpus.application.controller_profile import ControllerProfile
from korpus.application.predictive_evidence_control import PredictiveEvidenceController
from korpus.config import Settings


def build_predictive_controller(settings: Settings) -> PredictiveEvidenceController | None:
    if not settings.pec_enabled:
        return None
    if settings.pec_profile_path is None or not settings.pec_profile_sha256:
        return None
    profile = ControllerProfile.load(
        settings.pec_profile_path,
        expected_sha256=settings.pec_profile_sha256,
    )
    return PredictiveEvidenceController(profile, shadow_mode=settings.pec_shadow_mode)
