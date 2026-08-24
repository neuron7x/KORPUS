#!/usr/bin/env python3
"""Source/release-bound pytest collection manifests for deterministic regression sharding."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


def sha_lines(items: list[str]) -> str:
    return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()


def collect_nodeids(*, root: Path, env: dict[str, str], pytest_args: list[str]) -> list[str]:
    marker = "KORPUS_NODEIDS_JSON="
    collector = f"""import json, pytest, sys
class P:
    def pytest_collection_finish(self, session):
        print({marker!r} + json.dumps([item.nodeid for item in session.items], separators=(',', ':')))
p = P()
sys.exit(pytest.main(['--rootdir', {str(root)!r}, '--collect-only', '-q', *json.loads(sys.argv[1])], plugins=[p]))
"""
    completed = subprocess.run(
        [sys.executable, "-c", collector, json.dumps(pytest_args)],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"pytest collection failed ({completed.returncode}):\n{completed.stdout}\n{completed.stderr}")
    line = next((item for item in completed.stdout.splitlines() if item.startswith(marker)), "")
    nodeids = json.loads(line[len(marker):]) if line else []
    unique = sorted(set(str(item) for item in nodeids))
    if not unique or len(unique) != len(nodeids):
        raise RuntimeError(f"invalid pytest collection: total={len(nodeids)} unique={len(unique)}")
    return unique


def build_manifest(
    *,
    nodeids: list[str],
    release_tag: str,
    source_digest: str,
    pytest_args: list[str],
    python_version: str,
) -> dict[str, Any]:
    return {
        "schema": "korpus.regression-collection.v1",
        "release_tag": release_tag,
        "source_digest": source_digest,
        "collection_digest": sha_lines(nodeids),
        "collection_count": len(nodeids),
        "pytest_args": list(pytest_args),
        "python": python_version,
        "nodeids": list(nodeids),
    }


def validate_manifest(
    payload: dict[str, Any],
    *,
    release_tag: str,
    source_digest: str,
    pytest_args: list[str],
) -> list[str]:
    failures: list[str] = []
    nodeids = [str(item) for item in payload.get("nodeids", [])]
    if payload.get("schema") != "korpus.regression-collection.v1":
        failures.append("schema")
    if payload.get("release_tag") != release_tag:
        failures.append("release_tag")
    if payload.get("source_digest") != source_digest:
        failures.append("source_digest")
    if list(payload.get("pytest_args", [])) != list(pytest_args):
        failures.append("pytest_args")
    if not nodeids or len(nodeids) != len(set(nodeids)):
        failures.append("nodeids_unique_nonempty")
    if int(payload.get("collection_count", -1)) != len(nodeids):
        failures.append("collection_count")
    if payload.get("collection_digest") != sha_lines(nodeids):
        failures.append("collection_digest")
    return failures


def load_verified_manifest(
    path: Path,
    *,
    release_tag: str,
    source_digest: str,
    pytest_args: list[str],
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    failures = validate_manifest(
        payload,
        release_tag=release_tag,
        source_digest=source_digest,
        pytest_args=pytest_args,
    )
    if failures:
        raise RuntimeError("invalid regression collection manifest: " + ",".join(failures))
    return payload
