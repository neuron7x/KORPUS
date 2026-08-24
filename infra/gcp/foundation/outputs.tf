output "artifact_repository" {
  value = google_artifact_registry_repository.containers.name
}

output "cloud_sql_instance_name" {
  value = google_sql_database_instance.postgres.name
}

output "cloud_sql_connection_name" {
  value = google_sql_database_instance.postgres.connection_name
}

output "service_accounts" {
  value = {
    web      = google_service_account.web.email
    api      = google_service_account.api.email
    worker   = google_service_account.worker.email
    migrator = google_service_account.migrator.email
  }
}

output "buckets" {
  value = {
    objects    = google_storage_bucket.korpus["objects"].name
    quarantine = google_storage_bucket.korpus["quarantine"].name
    audit      = google_storage_bucket.korpus["audit"].name
    governance = google_storage_bucket.korpus["governance"].name
  }
}

output "secrets" {
  value = {
    db_admin        = google_secret_manager_secret.runtime["korpus-db-admin-password"].secret_id
    db_app          = google_secret_manager_secret.runtime["korpus-db-app-password"].secret_id
    audit_hmac      = google_secret_manager_secret.runtime["korpus-audit-hmac-key"].secret_id
    browser_session = google_secret_manager_secret.runtime["korpus-browser-session-key"].secret_id
    metrics_token   = google_secret_manager_secret.runtime["korpus-metrics-token"].secret_id
    oidc_client     = google_secret_manager_secret.runtime["korpus-oidc-client-secret"].secret_id
  }
}

output "object_retention_seconds" {
  value = var.object_retention_seconds
}

output "audit_retention_seconds" {
  value = var.audit_retention_seconds
}

output "edge_security_policy_self_link" {
  value = google_compute_security_policy.edge.self_link
}

output "runtime_network" {
  value = {
    name            = google_compute_network.runtime.name
    self_link       = google_compute_network.runtime.self_link
    subnetwork_name = google_compute_subnetwork.runtime.name
    subnetwork_link = google_compute_subnetwork.runtime.self_link
  }
}

output "cloud_sql_private_ip" {
  value = google_sql_database_instance.postgres.private_ip_address
}
