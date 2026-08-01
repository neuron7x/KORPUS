#!/usr/bin/env python3
"""Bounded concurrent soak and deterministic fault gate for browser OIDC."""
from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
from korpus.security.browser_oidc import (
    BrowserOIDCClient,
    BrowserSessionCodec,
    BrowserSessionError,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "var/resilience/browser-oidc-resilience.json"
SCENARIOS = ("success", "http_503", "invalid_json", "transport", "wrong_token_type")


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * quantile)]


def file_descriptors() -> int | None:
    path = Path("/proc/self/fd")
    return len(tuple(path.iterdir())) if path.is_dir() else None


def validate_report(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if report.get("schema") != "korpus.browser-oidc-resilience.v1":
        failures.append("DYN-SCHEMA")
    workload = report.get("workload", {})
    results = report.get("results", {})
    expected = workload.get("expected")
    observed = results.get("observed")
    if not isinstance(expected, dict) or observed != expected:
        failures.append("DYN-ORACLE")
    if results.get("raw_exceptions") != 0:
        failures.append("DYN-RAW-EXCEPTION")
    if results.get("codec_failures") != 0:
        failures.append("DYN-CODEC")
    if results.get("recovery_successes") != workload.get("recovery_operations"):
        failures.append("DYN-RECOVERY")
    if report.get("production_authorized") is not False:
        failures.append("DYN-PRODUCTION-AUTHORIZATION")
    expected_verdict = "PASS" if not failures else "FAIL"
    if report.get("verdict") != expected_verdict:
        failures.append("DYN-VERDICT-CONTRADICTION")
    return failures


def main() -> int:
    operations = int(os.getenv("KORPUS_OIDC_SOAK_OPERATIONS", "5000"))
    workers = int(os.getenv("KORPUS_OIDC_SOAK_WORKERS", "32"))
    recovery_operations = int(os.getenv("KORPUS_OIDC_RECOVERY_OPERATIONS", "200"))
    if not 100 <= operations <= 100_000 or not 1 <= workers <= 128:
        raise SystemExit("OIDC soak operations/workers are outside safe bounds")
    if not 10 <= recovery_operations <= 10_000:
        raise SystemExit("OIDC recovery operations are outside safe bounds")
    OUTPUT.unlink(missing_ok=True)

    def handler(request: httpx.Request) -> httpx.Response:
        code = parse_qs(request.content.decode())["code"][0]
        scenario = code.split("-", 1)[0]
        if scenario == "http_503":
            return httpx.Response(503, json={"error": "temporarily_unavailable"})
        if scenario == "invalid_json":
            return httpx.Response(200, content=b"not-json")
        if scenario == "transport":
            raise httpx.ConnectError("injected outage", request=request)
        token_type = "MAC" if scenario == "wrong_token_type" else "Bearer"
        return httpx.Response(
            200,
            json={
                "access_token": f"access-{code}",
                "id_token": f"identity-{code}",
                "expires_in": 300,
                "token_type": token_type,
            },
        )

    transport_client = httpx.Client(transport=httpx.MockTransport(handler))
    oidc = BrowserOIDCClient(
        authorization_endpoint="https://id.example/authorize",
        token_endpoint="https://id.example/token",
        client_id="resilience-client",
        redirect_uri="https://app.example/callback",
        scopes=["openid"],
        client=transport_client,
    )
    codec = BrowserSessionCodec("resilience-session-secret-000000000000", clock=lambda: 1_000)
    expected = {name: 0 for name in SCENARIOS}
    for index in range(operations):
        expected[SCENARIOS[index % len(SCENARIOS)]] += 1

    fd_before = file_descriptors()
    threads_before = threading.active_count()
    tracemalloc.start()
    started = time.perf_counter()

    def run(index: int) -> tuple[str, float, bool, bool]:
        scenario = SCENARIOS[index % len(SCENARIOS)]
        began = time.perf_counter_ns()
        codec_ok = False
        raw_exception = False
        try:
            token = codec.seal("session", {"index": index}, ttl_seconds=60)
            codec_ok = codec.open(token, expected_kind="session") == {"index": index}
            oidc.exchange(f"{scenario}-{index}", f"verifier-{index}")
            outcome = "success"
        except BrowserSessionError:
            outcome = scenario
        except Exception:
            outcome = "raw_exception"
            raw_exception = True
        return outcome, (time.perf_counter_ns() - began) / 1_000_000, codec_ok, raw_exception

    observed = {name: 0 for name in SCENARIOS}
    raw_exceptions = 0
    codec_failures = 0
    latencies: list[float] = []
    submission_window = workers * 4
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="oidc-soak") as pool:
        for start in range(0, operations, submission_window):
            stop = min(start + submission_window, operations)
            for outcome, latency, codec_ok, raw_exception in pool.map(run, range(start, stop)):
                if outcome in observed:
                    observed[outcome] += 1
                raw_exceptions += int(raw_exception)
                codec_failures += int(not codec_ok)
                latencies.append(latency)

    recovery_successes = 0
    for index in range(recovery_operations):
        try:
            oidc.exchange(f"success-recovery{index}", "recovery-verifier")
            recovery_successes += 1
        except Exception:
            pass
    duration = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    oidc.close()
    report: dict[str, Any] = {
        "schema": "korpus.browser-oidc-resilience.v1",
        "candidate_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip(),
        "workload": {
            "operations": operations,
            "workers": workers,
            "submission_window": submission_window,
            "recovery_operations": recovery_operations,
            "expected": expected,
        },
        "results": {
            "observed": observed,
            "raw_exceptions": raw_exceptions,
            "codec_failures": codec_failures,
            "recovery_successes": recovery_successes,
            "duration_seconds": duration,
            "throughput_operations_per_second": operations / duration,
            "latency_ms_p50": statistics.median(latencies),
            "latency_ms_p95": percentile(latencies, 0.95),
            "latency_ms_p99": percentile(latencies, 0.99),
            "latency_ms_max": max(latencies),
        },
        "resources": {
            "tracemalloc_peak_bytes": peak_bytes,
            "threads_before": threads_before,
            "threads_after": threading.active_count(),
            "file_descriptors_before": fd_before,
            "file_descriptors_after": file_descriptors(),
        },
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "limitations": [
            "Hermetic MockTransport protocol soak; no real IdP, socket pool or network impairment.",
            "Anchored local measurement; not a production SLO or week-long endurance claim.",
            "tracemalloc peak is diagnostic and is not an RSS or physical-energy measurement.",
        ],
        "production_authorized": False,
        "verdict": "PASS",
    }
    failures = validate_report(report)
    if failures:
        report["verdict"] = "FAIL"
        report["failures"] = failures
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = OUTPUT.with_suffix(".json.tmp")
    temporary_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary_output.replace(OUTPUT)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
