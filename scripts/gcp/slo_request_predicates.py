"""Request-based availability SLI predicates."""

from __future__ import annotations

from .slo_contract_types import Predicate, pred


def evaluate_request_sli(slo: str) -> list[Predicate]:
    return [
        pred(
            "SLO_LB_REQUEST_RATIO",
            "request_based_sli {" in slo
            and "good_total_ratio {" in slo
            and 'metric.type=\\"loadbalancing.googleapis.com/https/request_count\\"' in slo
            and 'resource.type=\\"https_lb_rule\\"' in slo
            and slo.count('resource.label.url_map_name=\\"${google_compute_url_map.https.name}\\"')
            == 2,
            "availability SLI is a request-based ratio scoped to the exact production HTTPS URL map",
        ),
        pred(
            "SLO_CLIENT_ERRORS_EXCLUDED",
            slo.count('metric.label.response_code_class!=\\"400\\"') == 2,
            "client 4xx responses are excluded from demanded-service and good-service filters",
        ),
        pred(
            "SLO_SERVICE_FAILURES_BAD",
            'metric.label.response_code_class!=\\"500\\"' in slo
            and 'metric.label.response_code_class!=\\"0\\"' in slo,
            "5xx and no-response class 0 consume error budget",
        ),
    ]
