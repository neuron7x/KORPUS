#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXACT = [
    ".gitlab-ci.yml",
    "docker-compose.yml",
    "apps/api/Dockerfile",
    "apps/web/Dockerfile",
    "apps/api/requirements.runtime.lock",
    "apps/api/requirements.dev.lock",
    "infra/otel-collector.yaml",
    "infra/minio/korpus-app-policy.json",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    paths = [ROOT / relative for relative in EXACT]
    paths.extend(sorted((ROOT / "deploy/kubernetes").rglob("*.yaml")))
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit(f"missing desired-state inputs: {missing}")
    records = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": digest(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(set(paths))
    ]
    root = hashlib.sha256()
    for record in records:
        root.update(str(record["path"]).encode() + b"\0" + str(record["sha256"]).encode() + b"\n")
    output = {
        "schema": "korpus.desired-state.v1",
        "release": "v5.0.0",
        "root_sha256": root.hexdigest(),
        "records": records,
        "interpretation": (
            "Source desired-state fingerprint only; "
            "live cluster drift requires external reconciliation."
        ),
    }
    target = ROOT / "config/operations/desired-state-v5.json"
    rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
            # "stale" alone sent the reader looking through eight inputs and a
            # kubernetes tree by hand. It is the message an author sees after every
            # edit to .gitlab-ci.yml, so it says which inputs moved and how to fix it.
            previous: dict[str, str] = {}
            if target.is_file():
                try:
                    stored = json.loads(target.read_text(encoding="utf-8"))
                    previous = {
                        str(item["path"]): str(item["sha256"])
                        for item in stored.get("records", [])
                    }
                except (json.JSONDecodeError, KeyError, TypeError):
                    previous = {}
            current = {str(item["path"]): str(item["sha256"]) for item in records}
            stale = {
                "valid": False,
                "reason": "desired-state manifest is stale",
                "changed": sorted(
                    path
                    for path in current.keys() | previous.keys()
                    if current.get(path) != previous.get(path)
                ),
                "regenerate_with": "python3 scripts/generate_desired_state.py",
            }
            print(json.dumps(stale, ensure_ascii=False, indent=2))
            return 1
    else:
        target.write_text(rendered, encoding="utf-8")
    summary = {"valid": True, "records": len(records), "root_sha256": output["root_sha256"]}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
