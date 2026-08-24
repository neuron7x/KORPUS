"""Private network-plane predicates for GCP production."""
from __future__ import annotations


def _direct_vpc(text: str) -> bool:
    return (
        'vpc_access {' in text
        and 'egress = "PRIVATE_RANGES_ONLY"' in text
        and 'network    = local.runtime_network.name' in text
        and 'subnetwork = local.runtime_network.subnetwork_name' in text
    )


def evaluate(s: object) -> list[tuple[str, bool, str]]:
    all_tf = s.all_tf
    return [
        (
            "PRIVATE_SERVICES_ACCESS",
            '"servicenetworking.googleapis.com"' in s.foundation
            and 'resource "google_compute_network" "runtime"' in all_tf
            and 'auto_create_subnetworks = false' in all_tf
            and 'resource "google_compute_global_address" "private_services"' in all_tf
            and 'purpose       = "VPC_PEERING"' in all_tf
            and 'resource "google_service_networking_connection" "private_services"' in all_tf
            and 'service                 = "servicenetworking.googleapis.com"' in all_tf,
            "dedicated custom VPC and Private Services Access peering exist for managed-service private IPs",
        ),
        (
            "CLOUDSQL_PRIVATE_ONLY",
            'ipv4_enabled    = false' in s.foundation
            and 'private_network = google_compute_network.runtime.id' in s.foundation
            and 'google_service_networking_connection.private_services' in s.foundation,
            "Cloud SQL public IPv4 is disabled and the instance is bound to the dedicated VPC after PSA establishment",
        ),
        (
            "RUNTIME_DIRECT_VPC_DB_PLANE",
            _direct_vpc(s.services)
            and _direct_vpc(s.worker)
            and _direct_vpc(s.migration)
            and _direct_vpc(s.postgres_verify)
            and s.services.count('vpc_access {') == 1
            and s.worker.count('vpc_access {') == 1
            and s.migration.count('vpc_access {') == 1
            and s.postgres_verify.count('vpc_access {') == 1,
            "API, ingestion worker, migration job, and PostgreSQL verifier use Direct VPC egress; web remains off the data-plane VPC",
        ),
        (
            "PRIVATE_NETWORK_STATE_BINDING",
            'output "runtime_network"' in all_tf
            and 'runtime_network   = local.foundation.runtime_network' in all_tf,
            "runtime consumes the network/subnet identity from immutable foundation remote state rather than duplicating names",
        ),
    ]
