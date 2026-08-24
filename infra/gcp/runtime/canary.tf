resource "google_cloud_run_v2_job" "candidate_probe" {
  project             = var.project_id
  name                = "korpus-candidate-probe"
  location            = var.region
  deletion_protection = true

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account       = local.service_accounts.web
      timeout               = "180s"
      max_retries           = 0
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

      # ALL_TRAFFIC + Private Google Access makes tagged run.app URLs traverse the
      # project VPC and therefore satisfy internal-and-load-balancing ingress.
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = local.runtime_network.name
          subnetwork = local.runtime_network.subnetwork_name
        }
      }

      containers {
        name    = "probe"
        image   = var.api_image
        command = ["python", "scripts/gcp/probe_candidate.py"]

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
    }
  }
}
