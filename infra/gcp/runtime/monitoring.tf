resource "google_monitoring_uptime_check_config" "edge" {
  project      = var.project_id
  display_name = "KORPUS production edge"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/healthz"
    port         = 443
    use_ssl      = true
    validate_ssl = true
    request_method = "GET"
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      host       = var.domain
      project_id = var.project_id
    }
  }

  content_matchers {
    content = "ok"
    matcher = "CONTAINS_STRING"
  }
}

resource "google_monitoring_alert_policy" "edge_unavailable" {
  project      = var.project_id
  display_name = "KORPUS edge unavailable"
  combiner     = "OR"
  notification_channels = var.notification_channel_ids

  conditions {
    display_name = "Uptime check failed"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\" AND resource.label.host=\"${var.domain}\" AND metric.label.check_id=\"${google_monitoring_uptime_check_config.edge.uptime_check_id}\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "120s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_NEXT_OLDER"
      }
    }
  }

  conditions {
    display_name = "Uptime telemetry absent"
    condition_absent {
      filter   = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\" AND metric.label.check_id=\"${google_monitoring_uptime_check_config.edge.uptime_check_id}\""
      duration = "300s"
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  documentation {
    content   = "KORPUS external HTTPS uptime check has failed for at least two minutes or stopped reporting for five minutes. Inspect Cloud Run, load balancer, Monitoring and Cloud SQL before changing traffic."
    mime_type = "text/markdown"
  }
}

# Cloud SQL provider-side pressure alarms remain available when application telemetry is not.
resource "google_monitoring_alert_policy" "cloudsql_disk_pressure" {
  project               = var.project_id
  display_name          = "KORPUS Cloud SQL disk pressure"
  combiner              = "OR"
  notification_channels = var.notification_channel_ids
  conditions {
    display_name = "Cloud SQL disk utilization above 80%"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/disk/utilization\" AND resource.type=\"cloudsql_database\" AND resource.label.database_id=\"${local.foundation.cloud_sql_instance_name}\" AND resource.label.region=\"${var.region}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8
      duration        = "300s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
  documentation {
    content   = "Cloud SQL disk utilization has remained above 80%. Verify growth, WAL/temp usage, retention and capacity before availability is affected."
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "cloudsql_memory_pressure" {
  project               = var.project_id
  display_name          = "KORPUS Cloud SQL memory pressure"
  combiner              = "OR"
  notification_channels = var.notification_channel_ids
  conditions {
    display_name = "Cloud SQL memory utilization above 90%"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/memory/utilization\" AND resource.type=\"cloudsql_database\" AND resource.label.database_id=\"${local.foundation.cloud_sql_instance_name}\" AND resource.label.region=\"${var.region}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.9
      duration        = "300s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
  documentation {
    content   = "Cloud SQL memory utilization has remained above 90%. Inspect working set, connection pressure and query behavior before resizing."
    mime_type = "text/markdown"
  }
}

# Worker Pools are non-HTTP. Sum active+idle instance series and compare with declared capacity.
resource "google_monitoring_alert_policy" "worker_capacity_missing" {
  project               = var.project_id
  display_name          = "KORPUS ingestion worker capacity missing"
  combiner              = "OR"
  notification_channels = var.notification_channel_ids
  conditions {
    display_name = "Worker Pool instance count below declared capacity"
    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/container/instance_count\" AND resource.type=\"cloud_run_worker_pool\" AND resource.label.worker_pool_name=\"korpus-ingestion\" AND resource.label.location=\"${var.region}\""
      comparison      = "COMPARISON_LT"
      threshold_value = var.worker_instances
      duration        = "300s"
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_MEAN"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.label.worker_pool_name"]
      }
    }
  }
  documentation {
    content   = "The ingestion Worker Pool has fewer live instances than the manually declared production capacity. Check revision health, startup probes and Cloud Run events."
    mime_type = "text/markdown"
  }
}

# Deep readiness crosses the API, Cloud SQL schema/RLS state, durable object store,
# and audit-anchor backlog. This is distinct from the shallow edge liveness check.
resource "google_monitoring_uptime_check_config" "api_ready" {
  project      = var.project_id
  display_name = "KORPUS production API readiness"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path           = "/api/ready"
    port           = 443
    use_ssl        = true
    validate_ssl   = true
    request_method = "GET"
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      host       = var.domain
      project_id = var.project_id
    }
  }

  content_matchers {
    content = "ready"
    matcher = "CONTAINS_STRING"
  }
}

resource "google_monitoring_alert_policy" "api_not_ready" {
  project               = var.project_id
  display_name          = "KORPUS API not ready"
  combiner              = "OR"
  notification_channels = var.notification_channel_ids

  conditions {
    display_name = "Deep readiness failed"
    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\"",
        "resource.type=\"uptime_url\"",
        "metric.label.check_id=\"${google_monitoring_uptime_check_config.api_ready.uptime_check_id}\"",
      ])
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "120s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_NEXT_OLDER"
      }
    }
  }

  conditions {
    display_name = "Deep readiness telemetry absent"
    condition_absent {
      filter = join(" AND ", [
        "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\"",
        "resource.type=\"uptime_url\"",
        "metric.label.check_id=\"${google_monitoring_uptime_check_config.api_ready.uptime_check_id}\"",
      ])
      duration = "300s"
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  documentation {
    content   = "KORPUS deep readiness has failed for at least two minutes or stopped reporting for five minutes. The /api/ready predicate crosses schema currency, Cloud SQL access, durable object-store health, and audit-anchor backlog; stop rollout and inspect the failing dependency."
    mime_type = "text/markdown"
  }
}


resource "google_monitoring_alert_policy" "tls_certificate_expiry" {
  project               = var.project_id
  display_name          = "KORPUS TLS certificate expiring"
  combiner              = "OR"
  notification_channels = var.notification_channel_ids

  conditions {
    display_name = "Production edge certificate expires within 15 days"
    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"monitoring.googleapis.com/uptime_check/time_until_ssl_cert_expires\"",
        "resource.type=\"uptime_url\"",
        "metric.label.check_id=\"${google_monitoring_uptime_check_config.edge.uptime_check_id}\"",
      ])
      comparison      = "COMPARISON_LT"
      threshold_value = 15
      duration        = "600s"

      aggregations {
        alignment_period   = "1200s"
        per_series_aligner = "ALIGN_NEXT_OLDER"
      }
    }
  }

  documentation {
    content   = "The TLS certificate observed by the production edge uptime check expires within 15 days. Verify managed-certificate provisioning, DNS authorization and load-balancer certificate attachment before expiry."
    mime_type = "text/markdown"
  }
}
