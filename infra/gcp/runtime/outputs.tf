output "edge_ip" {
  value = google_compute_global_address.edge.address
}

output "dns_a_record" {
  value = {
    name  = var.domain
    type  = "A"
    value = google_compute_global_address.edge.address
  }
}

output "web_service" {
  value = google_cloud_run_v2_service.web.name
}

output "api_service" {
  value = google_cloud_run_v2_service.api.name
}

output "migration_job" {
  value = google_cloud_run_v2_job.migrate.name
}

output "worker_pool" {
  value = google_cloud_run_v2_worker_pool.ingestion.name
}
