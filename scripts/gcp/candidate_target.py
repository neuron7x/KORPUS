#!/usr/bin/env python3
"""Resolve one immutable tagged Cloud Run candidate from a service description."""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

REVISION = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _candidate_url(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("candidate target lacks URL")
    parsed = urllib.parse.urlsplit(raw)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".run.app")
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("candidate URL must be a credential-free HTTPS run.app URL")
    return raw


def candidate(payload: dict[str, Any], tag: str = "candidate") -> dict[str, object]:
    traffic = payload.get("status", {}).get("traffic", [])
    matches = [item for item in traffic if isinstance(item, dict) and item.get("tag") == tag]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {tag!r} traffic target, got {len(matches)}")
    item = matches[0]
    revision = item.get("revisionName")
    percent = item.get("percent", 0)
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise ValueError("candidate target lacks a valid immutable revisionName")
    url = _candidate_url(item.get("url"))
    if not isinstance(percent, int) or isinstance(percent, bool) or not 0 <= percent <= 100:
        raise ValueError("candidate target has invalid percent")
    return {"tag": tag, "revision": revision, "url": url, "percent": percent}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--tag", default="candidate")
    parser.add_argument("--field", choices=("revision", "url", "percent"))
    args = parser.parse_args()
    payload = candidate(json.loads(args.snapshot.read_text(encoding="utf-8")), args.tag)
    print(payload[args.field] if args.field else json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
