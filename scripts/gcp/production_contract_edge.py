"""Cloud Armor and edge-routing predicates for the GCP production contract."""

from __future__ import annotations

import re


def evaluate(s: object) -> list[tuple[str, bool, str]]:
    edge_role = re.search(
        r'resource "google_project_iam_custom_role" "edge_policy_user".*?\n\}',
        s.foundation,
        re.S,
    )
    role_text = edge_role.group(0) if edge_role else ""
    waf_tokens = (
        "evaluatePreconfiguredWaf('sqli-v422-stable', {'sensitivity': 1})",
        "evaluatePreconfiguredWaf('xss-v422-stable', {'sensitivity': 1})",
        "evaluatePreconfiguredWaf('lfi-v422-stable', {'sensitivity': 1})",
        "evaluatePreconfiguredWaf('rce-v422-stable', {'sensitivity': 1})",
    )
    return [
        (
            "EDGE_CLOUD_ARMOR_ATTACHED",
            s.lb.count("security_policy       = local.foundation.edge_security_policy_self_link")
            == 2,
            "web and API backend services both attach the foundation-owned Cloud Armor policy",
        ),
        (
            "EDGE_WAF_ENFORCED",
            all(token in s.edge_security for token in waf_tokens)
            and s.edge_security.count("preview     = false") >= 4,
            "high-confidence OWASP CRS 4.22 SQLi/XSS/LFI/RCE rules enforce at sensitivity 1",
        ),
        (
            "EDGE_RATE_LIMIT_CALIBRATION",
            all(
                token in s.edge_security
                for token in (
                    'action      = "throttle"',
                    "preview     = true",
                    'enforce_on_key = "IP"',
                    "count        = 1200",
                    "interval_sec = 60",
                )
            ),
            "per-IP Cloud Armor throttle is present in preview for traffic-calibrated promotion",
        ),
        (
            "EDGE_FULL_REQUEST_LOGGING",
            s.lb.count("sample_rate = 1.0") == 2 and s.lb.count("enable      = true") == 2,
            "both external LB backends emit full request logs for WAF/rate-limit calibration and incident evidence",
        ),
        (
            "RUNTIME_EDGE_POLICY_LEAST_PRIVILEGE",
            '"compute.securityPolicies.get"' in role_text
            and '"compute.securityPolicies.use"' in role_text
            and "compute.securityPolicies.update" not in role_text
            and "compute.securityPolicies.delete" not in role_text,
            "runtime deployer may read/use but cannot mutate foundation-owned Cloud Armor policy",
        ),
    ]
