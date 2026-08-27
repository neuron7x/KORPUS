resource "google_cloud_run_v2_job" "embedding_backfill" {
  count               = var.embedding_backfill_enabled ? 1 : 0
  project             = var.project_id
  name                = "korpus-embedding-backfill"
  location            = var.region
  deletion_protection = true

  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account       = local.service_accounts.worker
      timeout               = "3600s"
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
        name = "embedding-token"
        secret {
          secret       = var.embedding_token_secret_id
          default_mode = 292
          items {
            version = "latest"
            path    = "token"
            mode    = 292
          }
        }
      }
      containers {
        name    = "embedding-backfill"
        image   = var.api_image
        command = ["/usr/local/bin/korpus-entrypoint"]
        args = ["python", "scripts/run_embedding_backfill.py", "--batch-size", tostring(var.embedding_backfill_batch_size), "--max-batches", tostring(var.embedding_backfill_max_batches), "--out", "/tmp/korpus/embedding-backfill-run.json"]
        resources {
          limits = { cpu = "2", memory = "2Gi" }
        }
        dynamic "env" {
          for_each = merge(local.worker_env, {
            KORPUS_EMBEDDING_ENDPOINT = var.embedding_endpoint
            KORPUS_EMBEDDING_MODEL_ID = var.embedding_model_id
            KORPUS_EMBEDDING_DIMENSIONS = tostring(var.embedding_dimensions)
            KORPUS_EMBEDDING_TOKEN_FILE = "/secrets/embedding/token"
            KORPUS_RUNTIME_IMAGE_REF = var.api_image
          })
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
          name       = "embedding-token"
          mount_path = "/secrets/embedding"
        }
      }
    }
  }
}
