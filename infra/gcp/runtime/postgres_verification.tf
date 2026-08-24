resource "google_cloud_run_v2_job" "postgres_verify" {
  project             = var.project_id
  name                = "korpus-postgres-verify"
  location            = var.region
  deletion_protection = true

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account       = local.service_accounts.migrator
      timeout               = "300s"
      max_retries           = 0
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

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
        name = "db-admin"
        secret {
          secret       = local.secrets.db_admin
          default_mode = 292
          items {
            version = "latest"
            path    = "password"
            mode    = 292
          }
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

      containers {
        name    = "postgres-verifier"
        image   = var.api_image
        command = ["/usr/local/bin/korpus-entrypoint"]
        args    = ["python", "scripts/gcp/verify_live_postgres.py", "--output", "-"]

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        env {
          name  = "KORPUS_DATABASE_URL_TEMPLATE"
          value = local.admin_database_url_template
        }
        env {
          name  = "KORPUS_DATABASE_PASSWORD_FILE"
          value = "/secrets/db-admin/password"
        }
        env {
          name  = "KORPUS_POSTGRES_APP_ROLE"
          value = "korpus_app"
        }
        env {
          name  = "KORPUS_POSTGRES_APP_PASSWORD_FILE"
          value = "/secrets/db-app/password"
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
        volume_mounts {
          name       = "db-admin"
          mount_path = "/secrets/db-admin"
        }
        volume_mounts {
          name       = "db-app"
          mount_path = "/secrets/db-app"
        }
      }
    }
  }
}
