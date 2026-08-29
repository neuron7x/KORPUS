"""Finite runtime-capacity predicates for production cost and blast-radius control."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the group modules are imported *by* production_contract, not before it
    from scripts.gcp.production_contract import Sources


def evaluate(s: Sources) -> list[tuple[str, bool, str]]:
    return [
        (
            "FINITE_RUNTIME_CAPACITY",
            "var.api_max_instances >= var.api_min_instances && var.api_max_instances <= 100"
            in s.runtime_vars
            and "var.web_max_instances >= var.web_min_instances && var.web_max_instances <= 100"
            in s.runtime_vars
            and "var.worker_instances >= 1 && var.worker_instances <= 20" in s.runtime_vars
            and "min_instance_count = var.api_min_instances" in s.services
            and "max_instance_count = var.api_max_instances" in s.services
            and "min_instance_count = var.web_min_instances" in s.services
            and "max_instance_count = var.web_max_instances" in s.services
            and "manual_instance_count = var.worker_instances" in s.worker,
            "API/web autoscaling and ingestion worker capacity have explicit finite operator-policy ceilings",
        )
    ]
