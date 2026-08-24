# Edge defense is a foundation control-plane resource so routine application
# delivery cannot weaken WAF/rate-limit policy. The global external Application
# Load Balancer backend services attach this policy by self-link.
resource "google_compute_security_policy" "edge" {
  project     = var.project_id
  name        = "korpus-edge-security"
  description = "KORPUS enforced high-confidence WAF with calibrated rate-limit preview"
  type        = "CLOUD_ARMOR"

  rule {
    priority    = 1000
    action      = "deny(403)"
    description = "OWASP CRS 4.22 SQL injection, sensitivity 1"
    preview     = false
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('sqli-v422-stable', {'sensitivity': 1})"
      }
    }
  }

  rule {
    priority    = 1010
    action      = "deny(403)"
    description = "OWASP CRS 4.22 XSS, sensitivity 1"
    preview     = false
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('xss-v422-stable', {'sensitivity': 1})"
      }
    }
  }

  rule {
    priority    = 1020
    action      = "deny(403)"
    description = "OWASP CRS 4.22 local-file inclusion, sensitivity 1"
    preview     = false
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('lfi-v422-stable', {'sensitivity': 1})"
      }
    }
  }

  rule {
    priority    = 1030
    action      = "deny(403)"
    description = "OWASP CRS 4.22 remote-code execution, sensitivity 1"
    preview     = false
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('rce-v422-stable', {'sensitivity': 1})"
      }
    }
  }

  # Rate limits require observed traffic calibration. Google recommends previewing
  # first deployments; the rule therefore produces evidence without risking an
  # uncalibrated availability failure. Promotion to enforcement is an explicit
  # post-observation change, not an inferred threshold.
  rule {
    priority    = 2000
    action      = "throttle"
    description = "Per-client abuse limiter; preview until production traffic calibration"
    preview     = true
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = 1200
        interval_sec = 60
      }
    }
  }

  rule {
    priority    = 2147483647
    action      = "allow"
    description = "Default allow after WAF/rate-limit evaluation"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
  }

  depends_on = [google_project_service.required]
}
