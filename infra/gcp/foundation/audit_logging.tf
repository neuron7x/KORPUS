# Data Access logs are explicitly enabled for high-value control/data planes whose
# unauthorized reads/writes must remain reconstructable. Admin Activity/System Event
# logs are already always on; this adds DATA_READ/DATA_WRITE where they matter most.
locals {
  data_access_audit_services = toset([
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "sqladmin.googleapis.com",
  ])
}

resource "google_project_iam_audit_config" "data_access" {
  for_each = local.data_access_audit_services
  project  = var.project_id
  service  = each.value

  audit_log_config {
    log_type = "DATA_READ"
  }

  audit_log_config {
    log_type = "DATA_WRITE"
  }
}
