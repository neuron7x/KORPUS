resource "google_compute_global_address" "edge" {
  project = var.project_id
  name    = "korpus-edge-ip"
}

resource "google_compute_region_network_endpoint_group" "web" {
  project               = var.project_id
  name                  = "korpus-web-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region

  cloud_run {
    service = google_cloud_run_v2_service.web.name
  }
}

resource "google_compute_region_network_endpoint_group" "api" {
  project               = var.project_id
  name                  = "korpus-api-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region

  cloud_run {
    service = google_cloud_run_v2_service.api.name
  }
}

resource "google_compute_backend_service" "web" {
  project               = var.project_id
  name                  = "korpus-web-backend"
  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec           = 30
  security_policy       = local.foundation.edge_security_policy_self_link

  log_config {
    enable      = true
    sample_rate = 1.0
  }

  backend {
    group = google_compute_region_network_endpoint_group.web.id
  }
}

resource "google_compute_backend_service" "api" {
  project               = var.project_id
  name                  = "korpus-api-backend"
  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec           = 60
  security_policy       = local.foundation.edge_security_policy_self_link

  log_config {
    enable      = true
    sample_rate = 1.0
  }

  backend {
    group = google_compute_region_network_endpoint_group.api.id
  }
}

resource "google_compute_url_map" "https" {
  project         = var.project_id
  name            = "korpus-https"
  default_service = google_compute_backend_service.web.id

  host_rule {
    hosts        = [var.domain]
    path_matcher = "korpus"
  }

  path_matcher {
    name            = "korpus"
    default_service = google_compute_backend_service.web.id

    route_rules {
      priority = 10
      service  = google_compute_backend_service.api.id
      match_rules {
        full_path_match = "/api"
      }
      route_action {
        url_rewrite {
          path_prefix_rewrite = "/"
        }
      }
    }

    route_rules {
      priority = 20
      service  = google_compute_backend_service.api.id
      match_rules {
        prefix_match = "/api/"
      }
      route_action {
        url_rewrite {
          path_prefix_rewrite = "/"
        }
      }
    }
  }

  test {
    host                = var.domain
    path                = "/api"
    service             = google_compute_backend_service.api.id
    expected_output_url = "https://${var.domain}/"
  }

  test {
    host                = var.domain
    path                = "/api/v1/auth/me"
    service             = google_compute_backend_service.api.id
    expected_output_url = "https://${var.domain}/v1/auth/me"
  }

  test {
    host    = var.domain
    path    = "/"
    service = google_compute_backend_service.web.id
  }
}

resource "google_compute_managed_ssl_certificate" "edge" {
  project = var.project_id
  name    = "korpus-edge-cert"
  managed {
    domains = [var.domain]
  }
}

resource "google_compute_ssl_policy" "edge" {
  project         = var.project_id
  name            = "korpus-edge-tls"
  profile         = "MODERN"
  min_tls_version = "TLS_1_2"
}

resource "google_compute_target_https_proxy" "edge" {
  project          = var.project_id
  name             = "korpus-https-proxy"
  url_map          = google_compute_url_map.https.id
  ssl_certificates = [google_compute_managed_ssl_certificate.edge.id]
  ssl_policy       = google_compute_ssl_policy.edge.id
}

resource "google_compute_global_forwarding_rule" "https" {
  project               = var.project_id
  name                  = "korpus-https"
  target                = google_compute_target_https_proxy.edge.id
  port_range            = "443"
  ip_address            = google_compute_global_address.edge.id
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

resource "google_compute_url_map" "http_redirect" {
  project = var.project_id
  name    = "korpus-http-redirect"
  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  project = var.project_id
  name    = "korpus-http-redirect"
  url_map = google_compute_url_map.http_redirect.id
}

resource "google_compute_global_forwarding_rule" "http" {
  project               = var.project_id
  name                  = "korpus-http"
  target                = google_compute_target_http_proxy.redirect.id
  port_range            = "80"
  ip_address            = google_compute_global_address.edge.id
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
