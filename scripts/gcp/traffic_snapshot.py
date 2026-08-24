#!/usr/bin/env python3
"""Canonicalize a Cloud Run service traffic snapshot for deterministic rollback."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any
def canonical_allocations(payload: dict[str, Any]) -> dict[str, int]:
    traffic = payload.get("status", {}).get("traffic", [])
    if not isinstance(traffic, list) or not traffic:
        raise ValueError("Cloud Run status.traffic is absent")
    allocations: dict[str, int] = {}
    for item in traffic:
        if not isinstance(item, dict):
            raise ValueError("traffic entry is not an object")
        revision = item.get("revisionName")
        percent = item.get("percent", 0)
        if not isinstance(revision, str) or not revision:
            if int(percent or 0) == 0:
                continue
            raise ValueError("positive traffic entry has no immutable revisionName")
        if not isinstance(percent, int) or isinstance(percent, bool) or percent < 0 or percent > 100:
            raise ValueError(f"invalid traffic percent for {revision}: {percent!r}")
        if percent:
            allocations[revision] = allocations.get(revision, 0) + percent
    if not allocations or sum(allocations.values()) != 100:
        raise ValueError(f"positive revision traffic must sum to 100, got {allocations}")
    return dict(sorted(allocations.items()))
def canonical_traffic(payload: dict[str, Any]) -> str:
    return ",".join(f"{revision}={percent}" for revision, percent in canonical_allocations(payload).items())
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--format", choices=("traffic", "terraform-json"), default="traffic")
    args = parser.parse_args()
    payload = json.loads(args.snapshot.read_text(encoding="utf-8"))
    allocations = canonical_allocations(payload)
    if args.format == "terraform-json":
        print(json.dumps(allocations, separators=(",", ":"), sort_keys=True))
    else:
        print(",".join(f"{revision}={percent}" for revision, percent in allocations.items()))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
