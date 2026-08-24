#!/usr/bin/env python3
"""Deterministic tagged-revision smoke probe executed from the production VPC."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Check:
    id: str
    passed: bool
    detail: str


def _base_url(raw: str) -> str:
    parsed = urllib.parse.urlsplit(raw)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".run.app")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("candidate URL must be a credential-free HTTPS run.app URL")
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _get(url: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "korpus-candidate-probe/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read(4096)
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(4096)


def evaluate(api_url: str, web_url: str, *, attempts: int, timeout: float) -> list[Check]:
    api = _base_url(api_url) + "/ready"
    web = _base_url(web_url) + "/healthz"
    checks: list[Check] = []
    for index in range(1, attempts + 1):
        try:
            status, body = _get(api, timeout)
            payload = json.loads(body)
            ok = status == 200 and payload == {"status": "ready"}
            checks.append(Check(f"API_READY_{index}", ok, f"status={status}"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            checks.append(Check(f"API_READY_{index}", False, type(exc).__name__))
        try:
            status, _ = _get(web, timeout)
            checks.append(Check(f"WEB_HEALTH_{index}", status == 200, f"status={status}"))
        except (urllib.error.URLError, TimeoutError) as exc:
            checks.append(Check(f"WEB_HEALTH_{index}", False, type(exc).__name__))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--web-url", required=True)
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    if not 1 <= args.attempts <= 20 or not 0.5 <= args.timeout <= 30:
        raise SystemExit("bounded attempts/timeout required")
    checks = evaluate(args.api_url, args.web_url, attempts=args.attempts, timeout=args.timeout)
    payload = {
        "schema": "korpus.candidate-probe.v1",
        "verdict": "PASS" if all(item.passed for item in checks) else "FAIL",
        "passed": sum(item.passed for item in checks),
        "total": len(checks),
        "checks": [asdict(item) for item in checks],
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
