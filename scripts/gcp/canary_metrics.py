#!/usr/bin/env python3
"""Fail-closed Cloud Run revision metric admission for staged production promotion."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.gcp.canary_numeric import request_count, validate_summary_policy, validate_timing

PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
REVISION = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class RevisionMetrics:
    service: str
    revision: str
    samples: int
    successful_requests: int
    server_errors: int
    error_rate: float
    passed: bool
    reason: str


def _access_token() -> str:
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        check=True,
        capture_output=True,
        text=True,
    )
    token = result.stdout.strip()
    if not token or any(ch.isspace() for ch in token):
        raise RuntimeError("gcloud returned an invalid access token")
    return token


def _request_count_payload(
    project: str,
    service: str,
    revision: str,
    *,
    start: datetime,
    end: datetime,
    token: str,
    timeout: float = 20.0,
) -> dict[str, Any]:
    metric_filter = " AND ".join(
        [
            'metric.type="run.googleapis.com/request_count"',
            'resource.type="cloud_run_revision"',
            f'resource.labels.service_name="{service}"',
            f'resource.labels.revision_name="{revision}"',
        ]
    )
    query = urllib.parse.urlencode(
        {
            "filter": metric_filter,
            "interval.startTime": start.isoformat().replace("+00:00", "Z"),
            "interval.endTime": end.isoformat().replace("+00:00", "Z"),
            "view": "FULL",
            "pageSize": "1000",
        }
    )
    url = f"https://monitoring.googleapis.com/v3/projects/{urllib.parse.quote(project, safe='')}/timeSeries?{query}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("Cloud Monitoring returned a non-object payload")
    if payload.get("nextPageToken"):
        raise RuntimeError(
            "request_count query exceeded one page; refusing incomplete admission evidence"
        )
    return payload


def _request_counts(payload: dict[str, Any]) -> tuple[int, int, int]:
    total = successes = errors = 0
    series = payload.get("timeSeries", [])
    if not isinstance(series, list):
        raise ValueError("timeSeries must be a list")
    for item in series:
        if not isinstance(item, dict):
            raise ValueError("timeSeries entry must be an object")
        labels = item.get("metric", {}).get("labels", {})
        response_class = labels.get("response_code_class", "") if isinstance(labels, dict) else ""
        points = item.get("points", [])
        if not isinstance(points, list):
            raise ValueError("timeSeries points must be a list")
        for point in points:
            value = point.get("value", {}) if isinstance(point, dict) else {}
            raw = value.get("int64Value", 0) if isinstance(value, dict) else 0
            count = request_count(raw)
            total += count
            successes += count if response_class == "2xx" else 0
            errors += count if response_class == "5xx" else 0
    return total, successes, errors


def summarize(
    payload: dict[str, Any],
    service: str,
    revision: str,
    minimum_samples: int,
    maximum_error_rate: float,
) -> RevisionMetrics:
    validate_summary_policy(minimum_samples, maximum_error_rate)
    total, successes, errors = _request_counts(payload)
    rate = errors / total if total else 0.0
    if successes < minimum_samples:
        return RevisionMetrics(
            service, revision, total, successes, errors, rate, False, "INSUFFICIENT_SUCCESS_SAMPLES"
        )
    if rate > maximum_error_rate:
        return RevisionMetrics(
            service, revision, total, successes, errors, rate, False, "SERVER_ERROR_RATE_EXCEEDED"
        )
    return RevisionMetrics(service, revision, total, successes, errors, rate, True, "PASS")


def _validate_policy(
    project: str,
    api_revision: str,
    web_revision: str,
    minimum_samples: int,
    maximum_error_rate: float,
    window_seconds: int,
    wait_seconds: int,
    poll_seconds: int,
) -> None:
    names_valid = all(
        (
            PROJECT_ID.fullmatch(project),
            REVISION.fullmatch(api_revision),
            REVISION.fullmatch(web_revision),
        )
    )
    if not names_valid:
        raise ValueError("project/revision identifiers do not satisfy Cloud resource-name policy")
    validate_summary_policy(minimum_samples, maximum_error_rate)
    validate_timing(window_seconds, wait_seconds, poll_seconds)


def evaluate(
    project: str,
    api_revision: str,
    web_revision: str,
    *,
    minimum_samples: int,
    maximum_error_rate: float,
    window_seconds: int,
    wait_seconds: int,
    poll_seconds: int,
) -> dict[str, Any]:
    _validate_policy(
        project,
        api_revision,
        web_revision,
        minimum_samples,
        maximum_error_rate,
        window_seconds,
        wait_seconds,
        poll_seconds,
    )
    deadline = time.monotonic() + wait_seconds
    last: list[RevisionMetrics] = []
    while True:
        now = datetime.now(UTC)
        start = now - timedelta(seconds=window_seconds)
        token = _access_token()
        last = [
            summarize(
                _request_count_payload(
                    project, "korpus-api", api_revision, start=start, end=now, token=token
                ),
                "korpus-api",
                api_revision,
                minimum_samples,
                maximum_error_rate,
            ),
            summarize(
                _request_count_payload(
                    project, "korpus-web", web_revision, start=start, end=now, token=token
                ),
                "korpus-web",
                web_revision,
                minimum_samples,
                maximum_error_rate,
            ),
        ]
        if all(item.passed for item in last):
            break
        if any(item.reason == "SERVER_ERROR_RATE_EXCEEDED" for item in last):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
    status = "PASS" if last and all(item.passed for item in last) else "FAIL"
    return {
        "status": status,
        "policy": {
            "minimum_samples": minimum_samples,
            "maximum_error_rate": maximum_error_rate,
            "window_seconds": window_seconds,
            "wait_seconds": wait_seconds,
            "poll_seconds": poll_seconds,
        },
        "revisions": [asdict(item) for item in last],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--api-revision", required=True)
    parser.add_argument("--web-revision", required=True)
    parser.add_argument("--minimum-samples", type=int, default=20)
    parser.add_argument("--maximum-error-rate", type=float, default=0.01)
    parser.add_argument("--window-seconds", type=int, default=600)
    parser.add_argument("--wait-seconds", type=int, default=240)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(
        args.project,
        args.api_revision,
        args.web_revision,
        minimum_samples=args.minimum_samples,
        maximum_error_rate=args.maximum_error_rate,
        window_seconds=args.window_seconds,
        wait_seconds=args.wait_seconds,
        poll_seconds=args.poll_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
