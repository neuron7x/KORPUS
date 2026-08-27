from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from korpus.application.numeric_contracts import finite_rate, strict_int

from .pec_revision_binding import RevisionBinding


@dataclass(frozen=True)
class CanaryVerdict:
    admitted: bool
    failures: tuple[str, ...]


def evaluate_canary(
    receipt: Mapping[str, object],
    *,
    binding: RevisionBinding,
    cloud_run_revision: str,
    minimum_samples: int,
    maximum_server_error_rate: float,
) -> CanaryVerdict:
    if not strict_int(minimum_samples) or minimum_samples < 1:
        raise ValueError("minimum_samples must be a positive integer")
    if not finite_rate(maximum_server_error_rate):
        raise ValueError("maximum_server_error_rate must be finite and in [0, 1]")
    failures: list[str] = []
    if str(receipt.get("release", "")) != binding.release:
        failures.append("release_mismatch")
    if str(receipt.get("cloud_run_revision", "")) != cloud_run_revision:
        failures.append("cloud_run_revision_mismatch")
    if str(receipt.get("environment_class", "")) != "PRODUCTION":
        failures.append("environment_not_production")
    samples = receipt.get("samples")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < minimum_samples:
        failures.append("insufficient_samples")
    rate = receipt.get("server_error_rate")
    if not finite_rate(rate) or float(rate) > maximum_server_error_rate:
        failures.append("server_error_rate")
    if receipt.get("human_judgment_admissible") is not True:
        failures.append("human_judgment_not_admissible")
    return CanaryVerdict(not failures, tuple(failures))
