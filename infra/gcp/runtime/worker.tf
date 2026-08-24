resource "google_cloud_run_v2_worker_pool" "ingestion" {
  project             = var.project_id
  name                = "korpus-ingestion"
  location            = var.region
  deletion_protection = true

  # Worker pools are a continuous pull runtime. Capacity is explicit and does not
  # pretend queue depth can be inferred from HTTP request traffic.
  scaling {
    scaling_mode         = "MANUAL"
    manual_instance_count = var.worker_instances
  }

  template {
    service_account = local.service_accounts.worker

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

    containers {
      name       = "worker"
      image      = var.api_image
      depends_on = ["clamav"]
      command    = ["python", "-m", "korpus.cli"]
      args       = ["worker-loop", "--idle-seconds", "1"]

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      dynamic "env" {
        for_each = local.worker_env
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
    }

    containers {
      name  = "clamav"
      image = var.clamav_image

      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
      }

      # depends_on is only meaningful if the dependency exposes a startup probe.
      startup_probe {
        initial_delay_seconds = 5
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 30
        tcp_socket {
          port = 3310
        }
      }
    }
  }

  instance_splits {
    type    = "INSTANCE_SPLIT_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}
