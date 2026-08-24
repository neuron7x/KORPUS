#!/usr/bin/env python3
"""Production edge smoke gate.

Validates DNS->edge binding, HTTPS certificate/hostname validation, web security
headers, and API readiness through the same public origin used by browsers.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Check:
    id: str
    passed: bool
    evidence: str


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _https_get(url: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "korpus-production-smoke/1"}
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return (
            response.status,
            {k.lower(): v for k, v in response.headers.items()},
            response.read(1_048_576),
        )


def evaluate(domain: str, expected_ip: str, timeout: float = 15.0) -> list[Check]:
    checks: list[Check] = []
    try:
        addrs = sorted({x[4][0] for x in socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)})
        dns_ok = expected_ip in addrs
        checks.append(
            Check("DNS_EDGE_BINDING", dns_ok, f"resolved={addrs}; expected={expected_ip}")
        )
    except OSError as exc:
        checks.append(Check("DNS_EDGE_BINDING", False, f"DNS failure: {exc}"))

    try:
        code, headers, body = _https_get(f"https://{domain}/healthz", timeout)
        checks.append(
            Check(
                "WEB_HEALTH",
                code == 200 and b"ok" in body.lower(),
                f"status={code}; body={body[:200]!r}",
            )
        )
        required = {
            "content-security-policy",
            "x-content-type-options",
            "x-frame-options",
            "referrer-policy",
        }
        missing = sorted(required - set(headers))
        checks.append(Check("WEB_SECURITY_HEADERS", not missing, f"missing={missing}"))
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        checks.append(Check("WEB_HEALTH", False, f"HTTPS/TLS failure: {exc}"))
        checks.append(Check("WEB_SECURITY_HEADERS", False, "web response unavailable"))

    try:
        code, headers, body = _https_get(f"https://{domain}/api/health", timeout)
        api_ok = code == 200
        try:
            payload = json.loads(body)
            api_ok = api_ok and isinstance(payload, dict)
        except json.JSONDecodeError:
            api_ok = False
        checks.append(Check("API_EDGE_READINESS", api_ok, f"status={code}; body={body[:500]!r}"))
        cache_control = headers.get("cache-control", "").lower()
        checks.append(
            Check(
                "API_NO_SHARED_CACHE",
                "no-store" in cache_control or "private" in cache_control,
                f"cache-control={cache_control!r}",
            )
        )
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        checks.append(Check("API_EDGE_READINESS", False, f"API HTTPS failure: {exc}"))
        checks.append(Check("API_NO_SHARED_CACHE", False, "API response unavailable"))

    opener = urllib.request.build_opener(NoRedirect)
    try:
        request = urllib.request.Request(f"http://{domain}/", method="GET")
        opener.open(request, timeout=timeout)
        checks.append(
            Check("HTTP_REDIRECT", False, "HTTP unexpectedly returned success without redirect")
        )
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location", "")
        checks.append(
            Check(
                "HTTP_REDIRECT",
                exc.code in {301, 302, 307, 308} and location.startswith(f"https://{domain}"),
                f"status={exc.code}; location={location}",
            )
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        checks.append(Check("HTTP_REDIRECT", False, f"HTTP redirect check failed: {exc}"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    parser.add_argument("--expected-ip", required=True)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output")
    args = parser.parse_args()
    checks = evaluate(args.domain, args.expected_ip, args.timeout)
    result = {
        "schema_version": "1.0",
        "verdict": "PASS" if all(x.passed for x in checks) else "FAIL",
        "passed": sum(x.passed for x in checks),
        "total": len(checks),
        "checks": [asdict(x) for x in checks],
    }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        from pathlib import Path

        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
