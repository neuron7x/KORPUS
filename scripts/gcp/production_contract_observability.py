"""Observability, audit, and autonomous-operations production predicates."""

from __future__ import annotations


def evaluate(s: object) -> list[tuple[str, bool, str]]:
    return [
        (
            "API_DEEP_READINESS_MONITOR",
            'resource "google_monitoring_uptime_check_config" "api_ready"' in s.monitoring
            and 'path           = "/api/ready"' in s.monitoring
            and "metric.label.check_id=" in s.monitoring
            and "google_monitoring_uptime_check_config.api_ready.uptime_check_id" in s.monitoring
            and 'resource "google_monitoring_alert_policy" "api_not_ready"' in s.monitoring,
            "external readiness check crosses API, schema/Cloud SQL, object store and audit backlog and pages on sustained failure",
        ),
        (
            "UPTIME_TELEMETRY_FAIL_CLOSED",
            s.monitoring.count("condition_absent {") >= 2
            and s.monitoring.count('duration = "300s"') >= 2
            and "google_monitoring_uptime_check_config.edge.uptime_check_id" in s.monitoring
            and "google_monitoring_uptime_check_config.api_ready.uptime_check_id" in s.monitoring,
            "edge and deep-readiness monitors page when their check_passed telemetry disappears for five minutes",
        ),
        (
            "TLS_EXPIRY_ALERT",
            'resource "google_monitoring_alert_policy" "tls_certificate_expiry"' in s.monitoring
            and "monitoring.googleapis.com/uptime_check/time_until_ssl_cert_expires" in s.monitoring
            and "threshold_value = 15" in s.monitoring
            and 'duration        = "600s"' in s.monitoring
            and "google_monitoring_uptime_check_config.edge.uptime_check_id" in s.monitoring,
            "production HTTPS certificate expiry is monitored against the exact edge uptime-check ID",
        ),
        (
            "DATA_ACCESS_AUDIT_LOGGING",
            'resource "google_project_iam_audit_config" "data_access"' in s.all_tf
            and all(
                svc in s.all_tf
                for svc in (
                    "secretmanager.googleapis.com",
                    "storage.googleapis.com",
                    "sqladmin.googleapis.com",
                )
            )
            and 'log_type = "DATA_READ"' in s.all_tf
            and 'log_type = "DATA_WRITE"' in s.all_tf,
            "Secret Manager, GCS and Cloud SQL Admin data-access reads/writes are explicitly auditable",
        ),
        (
            "AUTONOMOUS_ASSURANCE_SCHEDULE",
            'cron: "17 3 * * *"' in s.assurance_workflow,
            "full assurance campaign runs daily without operator initiation",
        ),
        (
            "AUTONOMOUS_PITR_DRILL_SCHEDULE",
            'cron: "37 3 1 * *"' in s.drill_workflow
            and "github.event_name == 'schedule'" in s.drill_workflow
            and "scripts/gcp/drill_cloudsql_pitr.sh" in s.drill_workflow,
            "PITR restore verification runs monthly in an isolated temporary clone",
        ),
        (
            "CLOUDSQL_DISK_ALERT",
            "cloudsql.googleapis.com/database/disk/utilization" in s.monitoring
            and "threshold_value = 0.8" in s.monitoring
            and "resource.label.database_id" in s.monitoring,
            "Cloud SQL disk pressure uses the GA utilization metric and the 80% threshold",
        ),
        (
            "CLOUDSQL_MEMORY_ALERT",
            "cloudsql.googleapis.com/database/memory/utilization" in s.monitoring
            and "threshold_value = 0.9" in s.monitoring,
            "Cloud SQL memory pressure uses the GA utilization metric and 90% ceiling",
        ),
        (
            "WORKER_CAPACITY_ALERT",
            "run.googleapis.com/container/instance_count" in s.monitoring
            and 'resource.type=\\"cloud_run_worker_pool\\"' in s.monitoring
            and "threshold_value = var.worker_instances" in s.monitoring
            and 'cross_series_reducer = "REDUCE_SUM"' in s.monitoring,
            "Worker Pool active+idle instance count is compared with declared manual capacity",
        ),
        (
            "DRILL_WORKFLOW_ACTION_PINS",
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in s.drill_workflow
            and "google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093"
            in s.drill_workflow,
            "DR workflow uses the same SHA-pinned checkout/auth trust set as production",
        ),
    ]
