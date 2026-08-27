#!/usr/bin/env python3
"""Best-effort-all, fail-closed Cloud Run traffic rollback executor."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
REVISION_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")


def validate_spec(spec: str) -> str:
    allocations: dict[str, int] = {}
    for item in spec.split(","):
        revision, sep, raw_percent = item.partition("=")
        if not sep or not REVISION_RE.fullmatch(revision) or not raw_percent.isdecimal():
            raise ValueError(f"invalid immutable traffic allocation: {item!r}")
        percent = int(raw_percent)
        if percent <= 0 or percent > 100 or revision in allocations:
            raise ValueError(f"invalid traffic allocation: {item!r}")
        allocations[revision] = percent
    if not allocations or sum(allocations.values()) != 100:
        raise ValueError(f"traffic allocation must sum exactly to 100: {allocations}")
    return ",".join(f"{revision}={allocations[revision]}" for revision in sorted(allocations))


def rollback_service(*, project: str, region: str, service: str, spec: str, evidence: Path) -> bool:
    if not SERVICE_RE.fullmatch(service):
        raise ValueError(f"invalid service name: {service!r}")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    if not spec:
        evidence.write_text(
            json.dumps({"service": service, "rollback": "not-applicable"}) + "\n", encoding="utf-8"
        )
        return True
    canonical = validate_spec(spec)
    result = subprocess.run(
        [
            "gcloud",
            "run",
            "services",
            "update-traffic",
            service,
            f"--project={project}",
            f"--region={region}",
            "--to-revisions",
            canonical,
            "--format=json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = {
                "service": service,
                "rollback": "invalid-gcloud-json",
                "stdout": result.stdout[:4096],
            }
            evidence.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            return False
        evidence.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return True
    error = evidence.with_suffix(".error.json")
    error.write_text(
        json.dumps(
            {"service": service, "returncode": result.returncode, "stderr": result.stderr[-4096:]},
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--api-spec", default="")
    parser.add_argument("--web-spec", default="")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    outcomes = []
    for service, spec, filename in (
        ("korpus-api", args.api_spec, "api-rollback.json"),
        ("korpus-web", args.web_spec, "web-rollback.json"),
    ):
        try:
            outcomes.append(
                rollback_service(
                    project=args.project,
                    region=args.region,
                    service=service,
                    spec=spec,
                    evidence=args.output_dir / filename,
                )
            )
        except (ValueError, OSError) as exc:
            (args.output_dir / f"{service}-rollback.error.json").write_text(
                json.dumps(
                    {"service": service, "error": type(exc).__name__, "detail": str(exc)},
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            outcomes.append(False)
    return 0 if all(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
