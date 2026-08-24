from __future__ import annotations

import shutil
from pathlib import Path

from scripts.gcp.slo_contract import evaluate

ROOT = Path(__file__).resolve().parents[3]


def _status(root: Path) -> dict[str, bool]:
    return {item.id: item.passed for item in evaluate(root)}


def _mutated(tmp_path: Path, relative: str, old: str, new: str) -> Path:
    for source in ["infra/gcp/runtime/slo.tf", "infra/gcp/runtime/variables.tf"]:
        destination = tmp_path / source
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source, destination)
    target = tmp_path / relative
    text = target.read_text(encoding="utf-8")
    assert old in text
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return tmp_path


def test_current_slo_contract_passes() -> None:
    status = _status(ROOT)
    assert status and all(status.values()), [name for name, ok in status.items() if not ok]


def test_lb_url_map_scope_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated(
        tmp_path,
        "infra/gcp/runtime/slo.tf",
        'resource.label.url_map_name=\\"${google_compute_url_map.https.name}\\"',
        'resource.label.url_map_name=\\"any\\"',
    )
    assert _status(root)["SLO_LB_REQUEST_RATIO"] is False


def test_5xx_failure_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated(
        tmp_path,
        "infra/gcp/runtime/slo.tf",
        'metric.label.response_code_class!=\\"500\\"',
        'metric.label.response_code_class!=\\"200\\"',
    )
    assert _status(root)["SLO_SERVICE_FAILURES_BAD"] is False


def test_fast_burn_threshold_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated(
        tmp_path, "infra/gcp/runtime/slo.tf", "threshold_value = 14.4", "threshold_value = 144"
    )
    assert _status(root)["SLO_FAST_BURN_MULTIWINDOW"] is False


def test_sustained_short_window_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated(tmp_path, "infra/gcp/runtime/slo.tf", '\\"30m\\"', '\\"3m\\"')
    assert _status(root)["SLO_SUSTAINED_BURN_MULTIWINDOW"] is False


def test_alert_delivery_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated(
        tmp_path,
        "infra/gcp/runtime/slo.tf",
        "notification_channels = var.notification_channel_ids",
        "# no delivery",
    )
    assert _status(root)["SLO_ALERT_DELIVERY_REQUIRED"] is False


def test_policy_target_must_remain_explicitly_tagged(tmp_path: Path) -> None:
    root = _mutated(tmp_path, "infra/gcp/runtime/variables.tf", "[EXTRAPOLATED_POLICY]", "")
    assert _status(root)["SLO_TARGET_IS_POLICY_VARIABLE"] is False
