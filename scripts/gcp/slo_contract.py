"""Static fail-closed predicates for the production SLO/error-budget contract."""

from __future__ import annotations

from pathlib import Path

from .slo_contract_types import Predicate, pred
from .slo_request_predicates import evaluate_request_sli


def evaluate(root: Path) -> list[Predicate]:
    slo = (root / "infra/gcp/runtime/slo.tf").read_text(encoding="utf-8")
    variables = (root / "infra/gcp/runtime/variables.tf").read_text(encoding="utf-8")
    return [
        pred(
            "SLO_CUSTOM_SERVICE",
            'resource "google_monitoring_custom_service" "edge"' in slo
            and 'service_id   = "korpus-edge"' in slo,
            "edge SLO is attached to an explicit Cloud Monitoring custom service",
        ),
        *evaluate_request_sli(slo),
        pred(
            "SLO_TARGET_IS_POLICY_VARIABLE",
            "goal                 = var.availability_slo_goal" in slo
            and "default     = 0.995" in variables
            and "[EXTRAPOLATED_POLICY]" in variables
            and "var.availability_slo_goal >= 0.99" in variables
            and "var.availability_slo_goal <= 0.999" in variables,
            "availability target is explicit, bounded and tagged as operator policy rather than measured fact",
        ),
        pred(
            "SLO_ROLLING_PERIOD_BOUNDED",
            "rolling_period_days  = var.availability_slo_rolling_days" in slo
            and "default     = 30" in variables
            and "var.availability_slo_rolling_days >= 1" in variables
            and "var.availability_slo_rolling_days <= 30" in variables,
            "rolling SLO period is configurable inside Cloud Monitoring's supported 1..30 day range",
        ),
        pred(
            "SLO_DELETE_PROTECTED",
            'deletion_policy      = "PREVENT"' in slo,
            "Terraform refuses accidental SLO deletion",
        ),
        pred(
            "SLO_FAST_BURN_MULTIWINDOW",
            'resource "google_monitoring_alert_policy" "slo_fast_burn"' in slo
            and 'combiner              = "AND"' in slo
            and r"\"60m\"" in slo
            and r"\"5m\"" in slo
            and slo.count("threshold_value = 14.4") == 2,
            "fast-burn page requires 14.4x burn in both 1h and 5m windows",
        ),
        pred(
            "SLO_SUSTAINED_BURN_MULTIWINDOW",
            'resource "google_monitoring_alert_policy" "slo_sustained_burn"' in slo
            and slo.count('combiner              = "AND"') == 2
            and r"\"6h\"" in slo
            and r"\"30m\"" in slo
            and slo.count("threshold_value = 6") == 2,
            "sustained page requires 6x burn in both 6h and 30m windows",
        ),
        pred(
            "SLO_BURN_USES_NATIVE_SELECTOR",
            slo.count("select_slo_burn_rate(") == 4
            and slo.count("google_monitoring_slo.edge_availability.name") == 4,
            "all burn alerts use Cloud Monitoring's native select_slo_burn_rate selector",
        ),
        pred(
            "SLO_ALERT_DELIVERY_REQUIRED",
            slo.count("notification_channels = var.notification_channel_ids") == 2,
            "each SLO burn-rate policy is bound to production notification channels",
        ),
    ]
