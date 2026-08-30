provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  services = toset([
    "artifactregistry.googleapis.com",
    "containeranalysis.googleapis.com",
    "containerscanning.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "servicenetworking.googleapis.com",
    "secretmanager.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each           = local.services
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "containers" {
  project       = var.project_id
  location      = var.region
  repository_id = "korpus"
  description   = "Canonical KORPUS production container images"
  format        = "DOCKER"

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "delete-untagged-after-30d"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "2592000s"
    }
  }

  cleanup_policies {
    id     = "retain-recent-versions"
    action = "KEEP"
    most_recent_versions {
      keep_count = 20
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_service_account" "web" {
  project      = var.project_id
  account_id   = "korpus-web"
  display_name = "KORPUS Web runtime"
}

resource "google_service_account" "api" {
  project      = var.project_id
  account_id   = "korpus-api"
  display_name = "KORPUS API runtime"
}

resource "google_service_account" "worker" {
  project      = var.project_id
  account_id   = "korpus-worker"
  display_name = "KORPUS ingestion worker"
}

resource "google_service_account" "migrator" {
  project      = var.project_id
  account_id   = "korpus-migrator"
  display_name = "KORPUS database migrator"
}

locals {
  runtime_service_account_resources = {
    web      = google_service_account.web.name
    api      = google_service_account.api.name
    worker   = google_service_account.worker.name
    migrator = google_service_account.migrator.name
  }
}

resource "google_service_account_iam_member" "github_deployer_act_as" {
  for_each = local.runtime_service_account_resources

  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.github_runtime_deployer_service_account}"
}

resource "google_service_account_iam_member" "gitlab_deployer_act_as" {
  for_each = local.runtime_service_account_resources

  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.gitlab_runtime_deployer_service_account}"
}

resource "google_sql_database_instance" "postgres" {
  project          = var.project_id
  name             = "${var.name_prefix}-postgres"
  region           = var.region
  database_version = "POSTGRES_17"

  deletion_protection = true

  lifecycle {
    prevent_destroy = true
    # Cloud SQL storage cannot shrink. Ignore the server-observed disk_size after an
    # automatic increase so a later plan never attempts to reconcile it downward.
    ignore_changes = [settings[0].disk_size]
  }

  settings {
    tier                        = var.database_tier
    availability_type           = "REGIONAL"
    disk_type                   = "PD_SSD"
    disk_size                   = var.database_disk_size_gb
    disk_autoresize             = true
    disk_autoresize_limit       = var.database_disk_autoresize_limit_gb
    deletion_protection_enabled = true
    connector_enforcement       = "REQUIRED"

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.runtime.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "02:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7

      backup_retention_settings {
        retained_backups = 14
        retention_unit   = "COUNT"
      }
    }

    insights_config {
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = true
      record_client_address   = false
    }

    maintenance_window {
      day          = 7
      hour         = 3
      update_track = "stable"
    }
  }

  depends_on = [google_project_service.required, google_service_networking_connection.private_services]
}

resource "google_sql_database" "korpus" {
  project  = var.project_id
  name     = "korpus"
  instance = google_sql_database_instance.postgres.name
}

locals {
  buckets = {
    objects = {
      suffix    = "objects"
      retention = var.object_retention_seconds
      locked    = var.lock_retention_policies
      versioned = true
    }
    quarantine = {
      suffix    = "quarantine"
      retention = 0
      locked    = false
      versioned = false
    }
    audit = {
      suffix    = "audit"
      retention = var.audit_retention_seconds
      locked    = var.lock_retention_policies
      versioned = true
    }
    governance = {
      suffix    = "governance"
      retention = var.governance_retention_seconds
      locked    = var.lock_retention_policies
      versioned = true
    }
  }
}

resource "google_storage_bucket" "korpus" {
  for_each = local.buckets

  project                     = var.project_id
  name                        = "${var.project_id}-korpus-${each.value.suffix}"
  location                    = "EU"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = each.value.versioned
  }

  dynamic "retention_policy" {
    for_each = each.value.retention > 0 ? [1] : []
    content {
      retention_period = each.value.retention
      is_locked        = each.value.locked
    }
  }

  dynamic "lifecycle_rule" {
    for_each = each.key == "quarantine" ? [1] : []
    content {
      action {
        type = "Delete"
      }
      condition {
        age = 7
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.required]
}

# Secret containers are IaC; secret payloads are deliberately not Terraform resources,
# preventing production credentials from entering Terraform state.
locals {
  secret_names = toset([
    "korpus-db-admin-password",
    "korpus-db-app-password",
    "korpus-audit-hmac-key",
    "korpus-browser-session-key",
    "korpus-metrics-token",
    "korpus-oidc-client-secret",
  ])
}

resource "google_secret_manager_secret" "runtime" {
  for_each  = local.secret_names
  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_project_iam_custom_role" "gcs_append_only" {
  project     = var.project_id
  role_id     = "korpusGcsAppendOnly"
  title       = "KORPUS GCS append-only object access"
  description = "Read/list/create without overwrite or delete. Retention is an independent control."
  permissions = [
    "storage.buckets.get",
    "storage.objects.create",
    "storage.objects.get",
    "storage.objects.list",
  ]
}

resource "google_project_iam_custom_role" "gcs_quarantine" {
  project     = var.project_id
  role_id     = "korpusGcsQuarantine"
  title       = "KORPUS GCS quarantine access"
  description = "Bucket metadata plus create/read/list; no overwrite, update, or delete."
  permissions = [
    "storage.buckets.get",
    "storage.objects.create",
    "storage.objects.get",
    "storage.objects.list",
  ]
}

locals {
  database_clients = {
    api      = google_service_account.api.email
    worker   = google_service_account.worker.email
    migrator = google_service_account.migrator.email
  }
}

resource "google_project_iam_member" "cloudsql_client" {
  for_each = local.database_clients
  project  = var.project_id
  role     = "roles/cloudsql.client"
  member   = "serviceAccount:${each.value}"
}

# API and worker can create/read immutable durable objects, but cannot delete or overwrite.
resource "google_storage_bucket_iam_member" "objects_append" {
  for_each = {
    api    = google_service_account.api.email
    worker = google_service_account.worker.email
  }
  bucket = google_storage_bucket.korpus["objects"].name
  role   = google_project_iam_custom_role.gcs_append_only.name
  member = "serviceAccount:${each.value}"
}

resource "google_storage_bucket_iam_member" "audit_append" {
  for_each = {
    api    = google_service_account.api.email
    worker = google_service_account.worker.email
  }
  bucket = google_storage_bucket.korpus["audit"].name
  role   = google_project_iam_custom_role.gcs_append_only.name
  member = "serviceAccount:${each.value}"
}

# Quarantine objects are lifecycle-expired by bucket policy. Runtime principals need
# create/read/list only; delete/update would expand blast radius without a code-path need.
resource "google_storage_bucket_iam_member" "quarantine_user" {
  for_each = {
    api    = google_service_account.api.email
    worker = google_service_account.worker.email
  }
  bucket = google_storage_bucket.korpus["quarantine"].name
  role   = google_project_iam_custom_role.gcs_quarantine.name
  member = "serviceAccount:${each.value}"
}

resource "google_storage_bucket_iam_member" "governance_viewer" {
  for_each = {
    api    = google_service_account.api.email
    worker = google_service_account.worker.email
  }
  bucket = google_storage_bucket.korpus["governance"].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${each.value}"
}

locals {
  secret_access = {
    "api-db"         = [google_service_account.api.email, "korpus-db-app-password"]
    "api-audit"      = [google_service_account.api.email, "korpus-audit-hmac-key"]
    "api-browser"    = [google_service_account.api.email, "korpus-browser-session-key"]
    "api-metrics"    = [google_service_account.api.email, "korpus-metrics-token"]
    "api-oidc"       = [google_service_account.api.email, "korpus-oidc-client-secret"]
    "worker-db"      = [google_service_account.worker.email, "korpus-db-app-password"]
    "worker-audit"   = [google_service_account.worker.email, "korpus-audit-hmac-key"]
    "migrator-admin" = [google_service_account.migrator.email, "korpus-db-admin-password"]
    "migrator-app"   = [google_service_account.migrator.email, "korpus-db-app-password"]
  }
}

resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = local.secret_access

  project   = var.project_id
  secret_id = google_secret_manager_secret.runtime[each.value[1]].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value[0]}"
}

# Routine application delivery deliberately excludes IAM/Secret Manager/Cloud SQL admin.
# It may mutate only the deployed application/edge plane and read scanner evidence.
locals {
  runtime_deployer_project_roles = toset([
    "roles/compute.loadBalancerAdmin",
    "roles/containeranalysis.occurrences.viewer",
    "roles/monitoring.editor",
    "roles/run.admin",
  ])
}

resource "google_project_iam_member" "runtime_deployer" {
  for_each = local.runtime_deployer_project_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${var.github_runtime_deployer_service_account}"
}

resource "google_project_iam_member" "gitlab_runtime_deployer" {
  for_each = local.runtime_deployer_project_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${var.gitlab_runtime_deployer_service_account}"
}

resource "google_artifact_registry_repository_iam_member" "runtime_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.containers.location
  repository = google_artifact_registry_repository.containers.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${var.github_runtime_deployer_service_account}"
}

resource "google_artifact_registry_repository_iam_member" "gitlab_runtime_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.containers.location
  repository = google_artifact_registry_repository.containers.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${var.gitlab_runtime_deployer_service_account}"
}

resource "google_storage_bucket_iam_member" "runtime_governance_creator" {
  bucket = google_storage_bucket.korpus["governance"].name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${var.github_runtime_deployer_service_account}"
}

resource "google_storage_bucket_iam_member" "runtime_governance_viewer" {
  bucket = google_storage_bucket.korpus["governance"].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.github_runtime_deployer_service_account}"
}

resource "google_storage_bucket_iam_member" "gitlab_runtime_governance_creator" {
  bucket = google_storage_bucket.korpus["governance"].name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${var.gitlab_runtime_deployer_service_account}"
}

resource "google_storage_bucket_iam_member" "gitlab_runtime_governance_viewer" {
  bucket = google_storage_bucket.korpus["governance"].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.gitlab_runtime_deployer_service_account}"
}

locals {
  drill_deployer_project_roles = toset([
    "roles/cloudsql.admin",
    "roles/run.developer",
    "roles/run.invoker",
  ])
}

resource "google_project_iam_member" "drill_deployer" {
  for_each = local.drill_deployer_project_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${var.github_drill_deployer_service_account}"
}

resource "google_artifact_registry_repository_iam_member" "drill_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.containers.location
  repository = google_artifact_registry_repository.containers.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${var.github_drill_deployer_service_account}"
}

resource "google_service_account_iam_member" "drill_migrator_act_as" {
  service_account_id = google_service_account.migrator.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.github_drill_deployer_service_account}"
}

resource "google_project_iam_member" "gitlab_drill_deployer" {
  for_each = local.drill_deployer_project_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${var.gitlab_drill_deployer_service_account}"
}

resource "google_artifact_registry_repository_iam_member" "gitlab_drill_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.containers.location
  repository = google_artifact_registry_repository.containers.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${var.gitlab_drill_deployer_service_account}"
}

resource "google_service_account_iam_member" "gitlab_drill_migrator_act_as" {
  service_account_id = google_service_account.migrator.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.gitlab_drill_deployer_service_account}"
}


# Routine delivery may attach the foundation-owned Cloud Armor policy to backend
# services, but cannot edit or delete the policy itself.
resource "google_project_iam_custom_role" "edge_policy_user" {
  project     = var.project_id
  role_id     = "korpusEdgePolicyUser"
  title       = "KORPUS Cloud Armor policy user"
  description = "Read/use the foundation-owned edge security policy without mutation rights."
  permissions = [
    "compute.securityPolicies.get",
    "compute.securityPolicies.use",
  ]
}

resource "google_project_iam_member" "runtime_edge_policy_user" {
  project = var.project_id
  role    = google_project_iam_custom_role.edge_policy_user.name
  member  = "serviceAccount:${var.github_runtime_deployer_service_account}"
}

resource "google_project_iam_member" "gitlab_runtime_edge_policy_user" {
  project = var.project_id
  role    = google_project_iam_custom_role.edge_policy_user.name
  member  = "serviceAccount:${var.gitlab_runtime_deployer_service_account}"
}
