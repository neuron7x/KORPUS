"""Pure promotion-admission predicates for PEC controller evidence."""

from collections.abc import Mapping

from korpus.application.controller_profile import ControllerProfile
from korpus.application.pec_promotion_bindings import promotion_binding_errors

REQUIRED_RECEIPTS = (
    "dataset_audit",
    "counterfactual_replay",
    "oracle",
    "training",
    "controller_verify",
    "ablation",
    "metamorphic",
    "mutation",
    "regression",
    "current_truth",
)


def promotion_errors(profile: ControllerProfile, statuses: Mapping[str, str]) -> list[str]:
    missing = sorted(set(REQUIRED_RECEIPTS) - set(statuses))
    nonpass = sorted(name for name, status in statuses.items() if status != "PASS")
    errors: list[str] = []
    if missing:
        errors.append(f"missing_receipts:{','.join(missing)}")
    if nonpass:
        errors.append(f"nonpass_receipts:{','.join(nonpass)}")
    if profile.admission_status != "PASS":
        errors.append("profile_not_admitted")
    return errors


__all__ = ["REQUIRED_RECEIPTS", "promotion_binding_errors", "promotion_errors"]
