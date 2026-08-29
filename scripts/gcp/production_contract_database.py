"""Cloud SQL production predicates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the group modules are imported *by* production_contract, not before it
    from scripts.gcp.production_contract import Sources


def evaluate(s: Sources) -> list[tuple[str, bool, str]]:
    return [
        (
            "CLOUDSQL_HA",
            'availability_type           = "REGIONAL"' in s.foundation,
            "Cloud SQL is REGIONAL HA",
        ),
        (
            "CLOUDSQL_CONNECTOR_ONLY",
            'connector_enforcement       = "REQUIRED"' in s.foundation,
            "Cloud SQL requires connectors",
        ),
        (
            "CLOUDSQL_BOUNDED_AUTOGROWTH",
            "disk_autoresize_limit       = var.database_disk_autoresize_limit_gb" in s.foundation
            and s.foundation.count("ignore_changes = [settings[0].disk_size]") == 1
            and s.foundation.count("prevent_destroy = true") >= 1
            and 'variable "database_disk_autoresize_limit_gb"' in s.foundation_vars
            and "var.database_disk_autoresize_limit_gb >= var.database_disk_size_gb"
            in s.foundation_vars
            and "TF_VAR_database_disk_autoresize_limit_gb: ${{ vars.KORPUS_DATABASE_DISK_AUTOSIZE_LIMIT_GB }}"
            in s.foundation_workflow,
            "Cloud SQL storage auto-growth has an explicit operator-owned finite ceiling and Terraform cannot reconcile server-side growth downward",
        ),
        (
            "CLOUDSQL_RECOVERY",
            all(
                token in s.foundation
                for token in (
                    "point_in_time_recovery_enabled = true",
                    "transaction_log_retention_days = 7",
                    "retained_backups = 14",
                    "deletion_protection = true",
                    "deletion_protection_enabled = true",
                )
            ),
            "PITR, transaction-log retention, retained backups, and dual deletion protection configured",
        ),
    ]
