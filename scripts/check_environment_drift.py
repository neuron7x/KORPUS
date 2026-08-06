#!/usr/bin/env python3
"""Compare a running environment against the approved desired state.

OPS-004. Two modes, and the difference between them is the whole point:

    --observe ROOT      fingerprint a deployed tree and write the observation
    --observation FILE  compare a previously written observation against the manifest

They are separate commands because the observation has to be taken *on the machine
that is running*, and the comparison has to be made against the manifest as committed.
Doing both in one process on the build host would fingerprint the build host — which is
the failure this check exists to catch, performed by the checker.

Exit codes: 0 in sync, 1 drift detected, 2 the check could not run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application import environment_drift  # noqa: E402

MANIFEST = ROOT / "config/operations/desired-state-v5.json"


def observe(root: Path, paths: list[str]) -> dict[str, Any]:
    """Fingerprint the declared paths as they exist under `root`.

    A path that is missing is reported as missing rather than omitted. Omitting it
    would make it UNOBSERVED — "we did not look" — when what happened is "we looked and
    it is gone", and those two carry different operator actions.
    """
    observed: dict[str, str | None] = {}
    for relative in paths:
        candidate = root / relative
        if candidate.is_file():
            observed[relative] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        else:
            observed[relative] = None
    return {
        "schema": "korpus.environment-observation.v1",
        # Stamped at observation time, on the host that was observed. Without it a
        # comparison cannot tell an observation taken before the change from one taken
        # after, and the verdict would be about whenever somebody last looked.
        "observed_at": datetime.now(UTC).isoformat(),
        "root": str(root),
        "observed": observed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe", type=Path, help="fingerprint this deployed tree")
    parser.add_argument("--out", type=Path, help="where to write the observation")
    parser.add_argument("--observation", type=Path, help="compare this observation")
    parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=environment_drift.DEFAULT_MAX_AGE_SECONDS,
        help="refuse an observation older than this",
    )
    args = parser.parse_args()

    if not MANIFEST.is_file():
        print(json.dumps({"valid": False, "reason": "no desired-state manifest"}))
        return 2
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    desired = environment_drift.desired_from_manifest(manifest)

    if args.observe is not None:
        payload = observe(args.observe, sorted(desired))
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if args.out is not None:
            # A fresh checkout has no var/. The script owns the path it was given:
            # asking every caller to mkdir first is how the check ends up wrapped in a
            # shell line that silently swallows its exit code.
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0

    if args.observation is None:
        print(
            json.dumps(
                {
                    "valid": False,
                    "reason": (
                        "no observation supplied. This check does not read a cluster; "
                        "run --observe on the deployed host first"
                    ),
                }
            )
        )
        return 2

    payload = json.loads(args.observation.read_text(encoding="utf-8"))
    observed = payload.get("observed")
    if not isinstance(observed, dict):
        print(json.dumps({"valid": False, "reason": "observation has no observed map"}))
        return 2

    fresh, freshness = environment_drift.observation_age_admissible(
        payload.get("observed_at"), datetime.now(UTC), args.max_age_seconds
    )
    if not fresh:
        # Refused rather than compared. A stale observation produces a verdict that
        # looks exactly like a current one, which is worse than no verdict.
        print(json.dumps({"valid": False, "reason": freshness}, ensure_ascii=False, indent=2))
        return 2

    report = environment_drift.compare(desired, observed)
    is_blocked, reason = environment_drift.blocked(report)
    output = report.as_dict()
    output["blocked"] = is_blocked
    output["reason"] = reason
    output["freshness"] = freshness
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if is_blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
