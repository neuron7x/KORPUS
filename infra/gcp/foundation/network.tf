# Dedicated production data-plane network. Cloud SQL has no public IPv4;
# Cloud Run workloads reach its private address through Direct VPC egress.
resource "google_compute_network" "runtime" {
  project                 = var.project_id
  name                    = "${var.name_prefix}-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.required]
}

resource "google_compute_subnetwork" "runtime" {
  project                  = var.project_id
  name                     = "${var.name_prefix}-runtime"
  region                   = var.region
  network                  = google_compute_network.runtime.id
  ip_cidr_range            = var.runtime_subnet_cidr
  private_ip_google_access = true
}

# Private Services Access is the Cloud SQL private-IP control-plane dependency.
# The address is Google-allocated from an unused RFC1918 range so this module does
# not invent a second fixed CIDR that could collide with the runtime subnet.
resource "google_compute_global_address" "private_services" {
  project       = var.project_id
  name          = "${var.name_prefix}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_service_range_prefix_length
  network       = google_compute_network.runtime.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.runtime.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]

  depends_on = [google_project_service.required]
}
