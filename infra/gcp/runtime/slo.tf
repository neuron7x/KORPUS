# Customer-visible edge availability objective.
# Policy target 0.995 is an initial operator SLO [EXTRAPOLATED_POLICY], not a claim
# about measured availability. Burn-rate thresholds are anchored to Google SRE guidance.
resource "google_monitoring_custom_service" "edge" {
  project      = var.project_id
  service_id   = "korpus-edge"
  display_name = "KORPUS production edge"
}

resource "google_monitoring_slo" "edge_availability" {
  project             = var.project_id
  service             = google_monitoring_custom_service.edge.service_id
  slo_id              = "edge-availability"
  display_name         = "KORPUS edge availability"
  goal                 = var.availability_slo_goal
  rolling_period_days  = var.availability_slo_rolling_days
  deletion_policy      = "PREVENT"

  request_based_sli {
    good_total_ratio {
      total_service_filter = join(" AND ", [
        "metric.type=\"loadbalancing.googleapis.com/https/request_count\"",
        "resource.type=\"https_lb_rule\"",
        "resource.label.url_map_name=\"${google_compute_url_map.https.name}\"",
        "metric.label.response_code_class!=\"400\"",
      ])
      good_service_filter = join(" AND ", [
        "metric.type=\"loadbalancing.googleapis.com/https/request_count\"",
        "resource.type=\"https_lb_rule\"",
        "resource.label.url_map_name=\"${google_compute_url_map.https.name}\"",
        "metric.label.response_code_class!=\"400\"",
        "metric.label.response_code_class!=\"500\"",
        "metric.label.response_code_class!=\"0\"",
      ])
    }
  }
}

# Google SRE Workbook starting point: 14.4x over 1h AND 5m (2% budget spend).
resource "google_monitoring_alert_policy" "slo_fast_burn" {
  project               = var.project_id
  display_name          = "KORPUS SLO fast burn"
  combiner              = "AND"
  notification_channels = var.notification_channel_ids

  conditions {
    display_name = "14.4x burn over 1h"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${google_monitoring_slo.edge_availability.name}\", \"60m\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 14.4
      duration        = "0s"
    }
  }

  conditions {
    display_name = "14.4x burn over 5m"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${google_monitoring_slo.edge_availability.name}\", \"5m\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 14.4
      duration        = "0s"
    }
  }

  documentation {
    content   = "KORPUS is consuming the edge availability error budget at >=14.4x in both 1h and 5m windows. Treat as page-level availability risk; inspect the public edge, Cloud Run and Cloud SQL before changing traffic."
    mime_type = "text/markdown"
  }
}

# Google SRE Workbook starting point: 6x over 6h AND 30m (5% budget spend).
resource "google_monitoring_alert_policy" "slo_sustained_burn" {
  project               = var.project_id
  display_name          = "KORPUS SLO sustained burn"
  combiner              = "AND"
  notification_channels = var.notification_channel_ids

  conditions {
    display_name = "6x burn over 6h"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${google_monitoring_slo.edge_availability.name}\", \"6h\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 6
      duration        = "0s"
    }
  }

  conditions {
    display_name = "6x burn over 30m"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${google_monitoring_slo.edge_availability.name}\", \"30m\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 6
      duration        = "0s"
    }
  }

  documentation {
    content   = "KORPUS is consuming the edge availability error budget at >=6x in both 6h and 30m windows. Treat as sustained reliability degradation and stop nonessential rollout changes until the burn normalizes."
    mime_type = "text/markdown"
  }
}
