#!/usr/bin/env python3
"""Fail-closed Artifact Analysis gate for immutable container image digests.

The live mode queries the Artifact Analysis v1 occurrences API using the current
`gcloud` identity.  A scan is acceptable only after a DISCOVERY occurrence is
FINISHED_SUCCESS/COMPLETE.  Vulnerability policy uses the highest package-level
effective severity when available, as recommended by Artifact Analysis.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SEVERITY_RANK = {
    "SEVERITY_UNSPECIFIED": 0,
    "MINIMAL": 1,
    "LOW": 2,
    "MEDIUM": 3,
    "HIGH": 4,
    "CRITICAL": 5,
}
TERMINAL_OK = {"FINISHED_SUCCESS", "COMPLETE"}
TERMINAL_BAD = {"FINISHED_FAILED", "FINISHED_UNSUPPORTED"}


class GateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Finding:
    note: str
    severity: str
    fix_available: bool
    packages: tuple[str, ...]


def _effective_severity(vulnerability: Mapping[str, Any]) -> str:
    package_issues = vulnerability.get("packageIssue") or []
    severities = [
        issue.get("effectiveSeverity", "SEVERITY_UNSPECIFIED")
        for issue in package_issues
        if isinstance(issue, Mapping)
    ]
    severities.append(
        vulnerability.get("effectiveSeverity")
        or vulnerability.get("severity")
        or "SEVERITY_UNSPECIFIED"
    )
    unknown = [s for s in severities if s not in SEVERITY_RANK]
    if unknown:
        raise GateError(f"unknown vulnerability severity values: {unknown!r}")
    return str(max(severities, key=SEVERITY_RANK.__getitem__))


def _finding(occ: Mapping[str, Any]) -> Finding:
    if occ.get("kind") != "VULNERABILITY":
        raise GateError("non-vulnerability occurrence passed to vulnerability parser")
    vulnerability = occ.get("vulnerability")
    if not isinstance(vulnerability, Mapping):
        raise GateError("VULNERABILITY occurrence lacks vulnerability details")
    packages: list[str] = []
    issue_fix: list[bool] = []
    for issue in vulnerability.get("packageIssue") or []:
        if not isinstance(issue, Mapping):
            raise GateError("malformed packageIssue")
        package = issue.get("affectedPackage")
        if package:
            packages.append(str(package))
        issue_fix.append(bool(issue.get("fixAvailable")))
    fix_available = bool(vulnerability.get("fixAvailable")) or any(issue_fix)
    return Finding(
        note=str(occ.get("noteName") or "UNKNOWN_NOTE"),
        severity=_effective_severity(vulnerability),
        fix_available=fix_available,
        packages=tuple(sorted(set(packages))),
    )


def evaluate(
    discovery: Iterable[Mapping[str, Any]],
    vulnerabilities: Iterable[Mapping[str, Any]],
    denied: set[str],
) -> dict[str, Any]:
    discovery = list(discovery)
    vulnerabilities = list(vulnerabilities)
    if not discovery:
        raise GateError("no DISCOVERY occurrence: scan completion is UNKNOWN")
    statuses: list[str] = []
    for occ in discovery:
        if occ.get("kind") != "DISCOVERY":
            raise GateError("non-DISCOVERY occurrence in discovery set")
        detail = occ.get("discovery")
        if not isinstance(detail, Mapping):
            raise GateError("DISCOVERY occurrence lacks discovery details")
        status = str(detail.get("analysisStatus") or "ANALYSIS_STATUS_UNSPECIFIED")
        statuses.append(status)
    if any(s in TERMINAL_BAD for s in statuses):
        raise GateError(f"scanner terminal failure: {statuses}")
    if not any(s in TERMINAL_OK for s in statuses):
        raise GateError(f"scanner not complete: {statuses}")

    findings = [_finding(x) for x in vulnerabilities]
    blocked = [f for f in findings if f.severity in denied]
    return {
        "schema_version": "1.0",
        "verdict": "PASS" if not blocked else "FAIL",
        "scan_statuses": statuses,
        "denied_severities": sorted(denied, key=SEVERITY_RANK.__getitem__),
        "finding_count": len(findings),
        "blocked_count": len(blocked),
        "findings": [asdict(x) for x in findings],
        "blocked": [asdict(x) for x in blocked],
    }


def _access_token() -> str:
    cp = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        check=True,
        text=True,
        capture_output=True,
    )
    token = cp.stdout.strip()
    if not token:
        raise GateError("gcloud returned an empty access token")
    return token


def _list_occurrences(
    project: str, resource_url: str, kind: str, token: str
) -> list[dict[str, Any]]:
    parent = f"projects/{project}"
    filter_expr = f'kind="{kind}" AND resourceUrl="{resource_url}"'
    base = f"https://containeranalysis.googleapis.com/v1/{parent}/occurrences"
    page_token = ""
    items: list[dict[str, Any]] = []
    while True:
        query = {"filter": filter_expr, "pageSize": "1000"}
        if page_token:
            query["pageToken"] = page_token
        request = urllib.request.Request(
            base + "?" + urllib.parse.urlencode(query),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except Exception as exc:  # network/auth/API failure is a hard gate
            raise GateError(f"Artifact Analysis query failed for {kind}: {exc}") from exc
        page = payload.get("occurrences", [])
        if not isinstance(page, list):
            raise GateError("Artifact Analysis returned malformed occurrences payload")
        items.extend(page)
        page_token = str(payload.get("nextPageToken") or "")
        if not page_token:
            return items


def _live(
    project: str, image: str, timeout_s: int, poll_s: int, denied: set[str]
) -> dict[str, Any]:
    if "@sha256:" not in image or image.count("@sha256:") != 1:
        raise GateError("image must be immutable and digest-pinned")
    digest = image.split("@sha256:", 1)[1]
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise GateError("invalid sha256 image digest")
    resource_url = "https://" + image
    token = _access_token()
    deadline = time.monotonic() + timeout_s
    while True:
        discovery = _list_occurrences(project, resource_url, "DISCOVERY", token)
        try:
            statuses = [str(x.get("discovery", {}).get("analysisStatus", "")) for x in discovery]
            if any(s in TERMINAL_BAD for s in statuses):
                return evaluate(discovery, [], denied)
            if any(s in TERMINAL_OK for s in statuses):
                vulnerabilities = _list_occurrences(project, resource_url, "VULNERABILITY", token)
                result = evaluate(discovery, vulnerabilities, denied)
                result["project"] = project
                result["image"] = image
                result["resource_url"] = resource_url
                return result
        except GateError:
            raise
        if time.monotonic() >= deadline:
            raise GateError(f"scan did not complete within {timeout_s}s; statuses={statuses}")
        time.sleep(poll_s)
        token = _access_token()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--image")
    ap.add_argument(
        "--fixture", type=Path, help="offline JSON containing discovery[] and vulnerabilities[]"
    )
    ap.add_argument("--deny-severity", action="append", default=["HIGH", "CRITICAL"])
    ap.add_argument("--timeout-seconds", type=int, default=600)
    ap.add_argument("--poll-seconds", type=int, default=10)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    denied = set(args.deny_severity)
    unknown = denied - set(SEVERITY_RANK)
    if unknown:
        print(f"FAIL: unknown denied severities: {sorted(unknown)}", file=sys.stderr)
        return 2
    try:
        if args.fixture:
            payload = json.loads(args.fixture.read_text(encoding="utf-8"))
            result = evaluate(
                payload.get("discovery", []), payload.get("vulnerabilities", []), denied
            )
        else:
            if not args.project or not args.image:
                raise GateError("live mode requires --project and --image")
            result = _live(
                args.project, args.image, args.timeout_seconds, args.poll_seconds, denied
            )
    except (GateError, json.JSONDecodeError, OSError, subprocess.CalledProcessError) as exc:
        result = {"schema_version": "1.0", "verdict": "FAIL", "error": str(exc)}
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
