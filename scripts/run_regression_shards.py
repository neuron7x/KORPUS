#!/usr/bin/env python3
"""Deterministic source/release-bound pytest regression sharding and exact merge gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "apps/api/src"))

from bounded_process import run_bounded  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from regression_collection import build_manifest, load_verified_manifest, sha_lines  # noqa: E402
from regression_collection import collect_nodeids as collect_manifest_nodeids  # noqa: E402
from release_identity import release_tag  # noqa: E402


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _env() -> dict[str, str]:
    env = os.environ.copy()
    parts = [str(ROOT / "apps/api/src"), str(ROOT / "scripts"), str(ROOT)]
    prior = env.get("PYTHONPATH")
    if prior:
        parts.append(prior)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env.setdefault("PYTHONHASHSEED", "0")
    return env


def collect_nodeids(pytest_args: list[str]) -> list[str]:
    collected = collect_manifest_nodeids(root=ROOT, env=_env(), pytest_args=pytest_args)
    return [str(nodeid) for nodeid in collected]


def prepare_collection(args: argparse.Namespace) -> int:
    source = compute_source_digest(ROOT)
    release = release_tag(ROOT)
    nodeids = collect_nodeids(args.pytest_args)
    payload = build_manifest(
        nodeids=nodeids,
        release_tag=release,
        source_digest=source,
        pytest_args=args.pytest_args,
        python_version=platform.python_version(),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: payload[k]
                for k in ("release_tag", "source_digest", "collection_digest", "collection_count")
            },
            indent=2,
        )
    )
    return 0


def bucket(nodeid: str, shard_count: int) -> int:
    return int.from_bytes(hashlib.sha256(nodeid.encode("utf-8")).digest()[:8], "big") % shard_count


def _junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    # pytest may write <testsuites> around one or more <testsuite> nodes.
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    fields = ("tests", "failures", "errors", "skipped")
    return {field: sum(int(s.attrib.get(field, "0")) for s in suites) for field in fields}


def run_shard(args: argparse.Namespace) -> int:
    source = compute_source_digest(ROOT)
    release = release_tag(ROOT)
    if args.collection_manifest:
        manifest = load_verified_manifest(
            args.collection_manifest,
            release_tag=release,
            source_digest=source,
            pytest_args=args.pytest_args,
        )
        nodeids = [str(item) for item in manifest["nodeids"]]
    else:
        nodeids = collect_nodeids(args.pytest_args)
    selected = [
        nodeid for nodeid in nodeids if bucket(nodeid, args.shard_count) == args.shard_index
    ]
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    junit = out.with_suffix(".junit.xml")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-q",
        f"--junitxml={junit}",
        *selected,
    ]
    started = time.monotonic()
    exit_code, stdout, stderr, timed_out, termination = run_bounded(
        cmd, cwd=ROOT, env=_env(), timeout_seconds=args.timeout_seconds
    )
    stdout_tail = "\n".join(stdout.splitlines()[-80:])
    stderr_tail = "\n".join(stderr.splitlines()[-80:])
    elapsed = time.monotonic() - started
    counts = (
        _junit_counts(junit)
        if junit.is_file()
        else {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    )
    status = (
        "UNKNOWN"
        if timed_out
        else (
            "PASS"
            if exit_code == 0
            and counts["tests"] == len(selected)
            and counts["failures"] == 0
            and counts["errors"] == 0
            else "FAIL"
        )
    )
    payload: dict[str, Any] = {
        "schema": "korpus.regression-shard.v1",
        "status": status,
        "release_tag": release,
        "source_digest": source,
        "collection_digest": sha_lines(nodeids),
        "collection_count": len(nodeids),
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "selected_count": len(selected),
        "selected_nodeids": selected,
        "selected_digest": _sha("\n".join(selected)),
        "junit": counts,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "termination": termination,
        "timeout_seconds": args.timeout_seconds,
        "elapsed_seconds": round(elapsed, 6),
        "python": platform.python_version(),
        "pytest_args": args.pytest_args,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: payload[k]
                for k in (
                    "status",
                    "source_digest",
                    "collection_count",
                    "shard_index",
                    "shard_count",
                    "selected_count",
                    "junit",
                    "timed_out",
                    "elapsed_seconds",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 1


def _single(values: set[Any]) -> Any | None:
    return next(iter(values)) if len(values) == 1 else None


def _receipt_identity(receipts: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    if not receipts:
        return {
            "release_tag": None,
            "source_digest": None,
            "collection_digest": None,
            "shard_count": 0,
        }, ["no_receipts"]
    fields: dict[str, set[Any]] = {
        "release_tag": {r.get("release_tag") for r in receipts},
        "source_digest": {r.get("source_digest") for r in receipts},
        "collection_digest": {r.get("collection_digest") for r in receipts},
        "shard_count": {r.get("shard_count") for r in receipts},
        "pytest_args": {json.dumps(r.get("pytest_args"), sort_keys=True) for r in receipts},
    }
    failures = [f"{name}_mismatch" for name, values in fields.items() if len(values) != 1]
    shard_count = _single(fields["shard_count"])
    counted = (
        shard_count if isinstance(shard_count, int) and not isinstance(shard_count, bool) else 0
    )
    return {
        "release_tag": _single(fields["release_tag"]),
        "source_digest": _single(fields["source_digest"]),
        "collection_digest": _single(fields["collection_digest"]),
        "shard_count": counted,
    }, failures


def _coverage_failures(
    receipts: list[dict[str, Any]], expected_shards: int
) -> tuple[list[str], list[str], int]:
    failures: list[str] = []
    indices = [int(r.get("shard_index", -1)) for r in receipts]
    if sorted(indices) != list(range(expected_shards)):
        failures.append("incomplete_or_duplicate_shards")
    if any(r.get("status") != "PASS" for r in receipts):
        failures.append("non_pass_shard")
    nodeids = [nodeid for r in receipts for nodeid in r.get("selected_nodeids", [])]
    if len(nodeids) != len(set(nodeids)):
        failures.append("duplicate_nodeids")
    expected_count = int(receipts[0].get("collection_count", 0)) if receipts else 0
    if len(nodeids) != expected_count:
        failures.append("coverage_count_mismatch")
    return nodeids, failures, expected_count


def _live_collection_failures(receipts: list[dict[str, Any]], nodeids: list[str]) -> list[str]:
    if not receipts:
        return []
    failures: list[str] = []
    expected_collection = collect_nodeids(list(receipts[0].get("pytest_args", [])))
    if _sha("\n".join(expected_collection)) != receipts[0].get("collection_digest"):
        failures.append("live_collection_digest_mismatch")
    if sorted(nodeids) != expected_collection:
        failures.append("exact_nodeid_coverage_mismatch")
    return failures


def _aggregate_junit(receipts: list[dict[str, Any]]) -> dict[str, int]:
    return {
        field: sum(int(r.get("junit", {}).get(field, 0)) for r in receipts)
        for field in ("tests", "failures", "errors", "skipped")
    }


def merge(args: argparse.Namespace) -> int:
    receipts = [json.loads(path.read_text(encoding="utf-8")) for path in args.receipts]
    identity, failures = _receipt_identity(receipts)
    nodeids, coverage_failures, expected_count = _coverage_failures(
        receipts, int(identity["shard_count"])
    )
    failures.extend(coverage_failures)
    failures.extend(_live_collection_failures(receipts, nodeids))
    counts = _aggregate_junit(receipts)
    if counts["tests"] != expected_count:
        failures.append("junit_test_count_mismatch")
    payload = {
        "schema": "korpus.regression-merge.v1",
        "status": "PASS" if not failures else "FAIL",
        "release_tag": identity["release_tag"],
        "source_digest": identity["source_digest"],
        "collection_digest": identity["collection_digest"],
        "collection_count": expected_count,
        "shards": identity["shard_count"],
        "junit": counts,
        "failures": failures,
        "receipt_paths": [str(p) for p in args.receipts],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("pytest_args", nargs="*", default=[])
    run = sub.add_parser("run")
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--shard-count", type=int, required=True)
    run.add_argument("--timeout-seconds", type=int, default=240)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--collection-manifest", type=Path)
    run.add_argument("pytest_args", nargs="*", default=[])
    merge_parser = sub.add_parser("merge")
    merge_parser.add_argument("--out", type=Path, required=True)
    merge_parser.add_argument("receipts", nargs="+", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        return prepare_collection(args)
    if args.command == "run":
        if args.shard_count < 1 or not (0 <= args.shard_index < args.shard_count):
            parser.error("invalid shard index/count")
        return run_shard(args)
    return merge(args)


if __name__ == "__main__":
    raise SystemExit(main())
