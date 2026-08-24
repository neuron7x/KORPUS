"""TLS edge predicates for GCP production delivery."""
from __future__ import annotations

def evaluate(s: object) -> list[tuple[str, bool, str]]:
    return [
        (
            "EDGE_TLS_POLICY_ENFORCED",
            'resource "google_compute_ssl_policy" "edge"' in s.lb
            and 'profile         = "MODERN"' in s.lb
            and 'min_tls_version = "TLS_1_2"' in s.lb
            and 'ssl_policy       = google_compute_ssl_policy.edge.id' in s.lb,
            "global HTTPS proxy is bound to an explicit MODERN TLS policy with TLS 1.2 minimum",
        )
    ]
