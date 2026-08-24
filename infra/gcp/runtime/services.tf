provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_cloud_run_v2_service" "web" {
  project             = var.project_id
  name                = "korpus-web"
  location            = var.region
  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  scaling {
    min_instance_count = var.web_min_instances
    max_instance_count = var.web_max_instances
  }

  template {
    service_account = local.service_accounts.web
    timeout         = "30s"

    containers {
      name  = "web"
      image = var.web_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 2
        period_seconds        = 3
        failure_threshold     = 10
        http_get {
          path = "/healthz"
          port = 8080
        }
      }

      liveness_probe {
        timeout_seconds   = 2
        period_seconds    = 30
        failure_threshold = 3
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }

  dynamic "traffic" {
    for_each = var.web_stable_traffic
    content {
      type     = "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION"
      revision = traffic.key
      percent  = traffic.value
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = length(var.web_stable_traffic) == 0 ? 100 : 0
    tag     = "candidate"
  }
}

resource "google_cloud_run_v2_service" "api" {
  project             = var.project_id
  name                = "korpus-api"
  location            = var.region
  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  scaling {
    min_instance_count = var.api_min_instances
    max_instance_count = var.api_max_instances
  }

  template {
    service_account                 = local.service_accounts.api
    timeout                         = "60s"
    execution_environment           = "EXECUTION_ENVIRONMENT_GEN2"
    max_instance_request_concurrency = 40

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = local.runtime_network.name
        subnetwork = local.runtime_network.subnetwork_name
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [local.cloud_sql_name]
      }
    }

    volumes {
      name = "governance"
      gcs {
        bucket        = local.buckets.governance
        read_only     = true
        mount_options = ["uid=10001", "gid=10001", "file-mode=0444", "dir-mode=0555"]
      }
    }

    volumes {
      name = "db-app"
      secret {
        secret       = local.secrets.db_app
        default_mode = 292
        items {
          version = "latest"
          path    = "password"
          mode    = 292
        }
      }
    }

    volumes {
      name = "audit-hmac"
      secret {
        secret       = local.secrets.audit_hmac
        default_mode = 292
        items {
          version = "latest"
          path    = "key"
          mode    = 292
        }
      }
    }

    volumes {
      name = "browser-session"
      secret {
        secret       = local.secrets.browser_session
        default_mode = 292
        items {
          version = "latest"
          path    = "key"
          mode    = 292
        }
      }
    }

    volumes {
      name = "metrics"
      secret {
        secret       = local.secrets.metrics_token
        default_mode = 292
        items {
          version = "latest"
          path    = "token"
          mode    = 292
        }
      }
    }

    volumes {
      name = "oidc-client"
      secret {
        secret       = local.secrets.oidc_client
        default_mode = 292
        items {
          version = "latest"
          path    = "secret"
          mode    = 292
        }
      }
    }

    containers {
      name  = "api"
      image = var.api_image

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
        cpu_idle          = false
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.api_env
        content {
          name  = env.key
          value = env.value
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
      volume_mounts {
        name       = "governance"
        mount_path = "/etc/korpus/governance"
      }
      volume_mounts {
        name       = "db-app"
        mount_path = "/secrets/db-app"
      }
      volume_mounts {
        name       = "audit-hmac"
        mount_path = "/secrets/audit-hmac"
      }
      volume_mounts {
        name       = "browser-session"
        mount_path = "/secrets/browser-session"
      }
      volume_mounts {
        name       = "metrics"
        mount_path = "/secrets/metrics"
      }
      volume_mounts {
        name       = "oidc-client"
        mount_path = "/secrets/oidc-client"
      }

      startup_probe {
        initial_delay_seconds = 1
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          # Deep readiness exercises Cloud SQL + object-store connectivity before
          # this revision is eligible to accept production traffic.
          path = "/ready"
          port = 8000
        }
      }

      liveness_probe {
        timeout_seconds   = 3
        period_seconds    = 30
        failure_threshold = 3
        http_get {
          path = "/health"
          port = 8000
        }
      }
    }
  }

  dynamic "traffic" {
    for_each = var.api_stable_traffic
    content {
      type     = "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION"
      revision = traffic.key
      percent  = traffic.value
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = length(var.api_stable_traffic) == 0 ? 100 : 0
    tag     = "candidate"
  }
}

# The external load balancer is the only network ingress, while application OIDC/BFF
# remains the end-user authorization boundary. Cloud Run itself therefore accepts the
# LB's unauthenticated invocation, but direct public run.app ingress is denied above.
resource "google_cloud_run_v2_service_iam_member" "web_public_lb" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "api_public_lb" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
