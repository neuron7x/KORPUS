#!/usr/bin/env python3
"""Build one hosted execution attestation from evidence produced in the same run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.github_assurance_receipts import (  # noqa: E402
    canonical_identity,
    identity_from_environment,
    new_receipt,
)
from korpus.application.junit_contracts import junit_counts  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from korpus.application.release_claim_hosted import (  # noqa: E402
    CLAIM_EXECUTORS,
    allowed_source_ref,
    new_attestation,
)
from release_claim_projection import (  # noqa: E402
    inference_projection as _inference_projection,
)
from release_claim_projection import (  # noqa: E402
    mutation_execution_valid as _mutation_execution_valid,
)
from release_claim_projection import (  # noqa: E402
    mutation_projection as _mutation_projection,
)
from release_claim_projection import stable_web as _stable_web  # noqa: E402
from release_claim_projection import (  # noqa: E402
    web_execution_valid as _web_execution_valid,
)
from release_identity import release_tag  # noqa: E402

ATTESTATION_NAME = "RELEASE_CLAIM_ATTESTATION.json"
RECEIPT_NAME = "RELEASE_CLAIM_RECEIPT.json"
_JUNIT_FIELDS = ("tests", "failures", "errors", "skipped")


@dataclass(frozen=True)
class HostedInputs:
    sqlite_junit: Path
    mutation: Path
    inference: Path
    inference_junit: Path
    web: Path
    web_tap: Path
    out_dir: Path


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON object: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON payload is not an object: {path}")
    return value


def _junit(path: Path) -> dict[str, int]:
    try:
        root = ET.parse(path).getroot()
        counts = junit_counts(root)
    except (OSError, ET.ParseError, ValueError) as error:
        raise ValueError(f"invalid JUnit evidence: {path}") from error
    cases = list(root.iter("testcase"))
    observed = {
        "tests": len(cases),
        "failures": sum(child.tag == "failure" for case in cases for child in case),
        "errors": sum(child.tag == "error" for case in cases for child in case),
        "skipped": sum(child.tag == "skipped" for case in cases for child in case),
    }
    if counts != observed or counts["tests"] < 1 or counts["failures"] or counts["errors"]:
        raise ValueError(f"JUnit evidence is empty, failing, or structurally inconsistent: {path}")
    return {field: int(counts[field]) for field in _JUNIT_FIELDS}


def _tap(path: Path) -> tuple[dict[str, int], str]:
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"invalid TAP evidence: {path}") from error
    counts: dict[str, int] = {}
    for key in ("tests", "pass", "fail", "skipped"):
        matches = re.findall(rf"^# {key} (\d+)$", text, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError(f"TAP evidence has {len(matches)} {key} summaries: {path}")
        counts[key] = int(matches[0])
    plans = re.findall(r"^1\.\.(\d+)(?:\s.*)?$", text, re.MULTILINE)
    assertions = re.findall(r"^(not ok|ok)\s+(\d+)([^\r\n]*)$", text, re.MULTILINE)
    numbers = [int(number) for _status, number, _tail in assertions]
    assertion_failures = sum(status == "not ok" for status, _number, _tail in assertions)
    assertion_skips = sum("# skip" in tail.lower() for _status, _number, tail in assertions)
    assertion_passes = len(assertions) - assertion_failures - assertion_skips
    structural = (
        len(plans) == 1
        and int(plans[0]) == counts["tests"]
        and numbers == list(range(1, counts["tests"] + 1))
        and re.search(r"^\s*Bail out!", text, re.MULTILINE | re.IGNORECASE) is None
        and "# todo" not in "\n".join(tail.lower() for _status, _number, tail in assertions)
        and assertion_passes == counts["pass"]
        and assertion_failures == counts["fail"]
        and assertion_skips == counts["skipped"]
    )
    if (
        counts["tests"] < 1
        or counts["fail"]
        or counts["tests"] != counts["pass"] + counts["fail"] + counts["skipped"]
        or not structural
    ):
        raise ValueError(f"TAP evidence is empty, failing, or arithmetically invalid: {path}")
    return counts, hashlib.sha256(payload).hexdigest()


def _provenance(payload: Mapping[str, Any], source: str, generator: str) -> bool:
    value = payload.get("provenance")
    return bool(
        isinstance(value, Mapping)
        and type(value.get("schema_version")) is int
        and value.get("schema_version") == 1
        and value.get("source_digest") == source
        and value.get("digest_scope") == "evidence_paths"
        and value.get("generator") == generator
        and isinstance(value.get("generated_at"), str)
        and value["generated_at"]
    )


def _tracked(root: Path, paths: Sequence[str]) -> None:
    if not paths or len(paths) != len(set(paths)):
        raise ValueError("canonical artifact paths are empty or duplicated")
    run = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    if run.returncode != 0 or set(run.stdout.splitlines()) != set(paths):
        raise ValueError("release-claim artifacts are not the exact tracked path set")


def _backend_execution(root: Path, release: str, source: str, sqlite_junit: Path) -> dict[str, Any]:
    evidence = f"reports/release/{release}/FULL_BACKEND_REPORT.json"
    merge_path = "reports/regression/FULL_REGRESSION_CURRENT.json"
    report, merge = _object(root / evidence), _object(root / merge_path)
    counts = _junit(sqlite_junit)
    shards = merge.get("shards")
    if not isinstance(shards, int) or isinstance(shards, bool) or shards < 1:
        raise ValueError("canonical regression merge has no positive shard count")
    expected_report = {
        "schema": "korpus.full-backend-report.v2",
        "status": "PASS",
        "release": release,
        "source_tree_sha256": source,
        "digest_scope": "evidence_paths",
        "collection_digest": merge.get("collection_digest"),
        "collected": merge.get("collection_count"),
        "passed": counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"],
        "failed": counts["failures"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "shards": shards,
        "evidence_source": merge_path,
    }
    if (
        report != expected_report
        or merge.get("schema") != "korpus.regression-merge.v1"
        or merge.get("status") != "PASS"
        or merge.get("release_tag") != release
        or merge.get("source_digest") != source
        or merge.get("collection_count") != counts["tests"]
        or merge.get("junit") != counts
        or merge.get("failures") != []
    ):
        raise ValueError("hosted SQLite execution disagrees with canonical backend evidence")
    json_paths = [f"reports/regression/shards/shard-{index}.json" for index in range(shards)]
    junit_paths = [f"reports/regression/shards/shard-{index}.junit.xml" for index in range(shards)]
    artifacts = [evidence, merge_path, *json_paths, *junit_paths]
    _tracked(root, artifacts)
    return {
        "executor": "backend",
        "exit_code": 0,
        "result": {
            **counts,
            "collection_digest": merge["collection_digest"],
            "shards": shards,
        },
        "artifacts": artifacts,
    }


def _mutation_execution(root: Path, source: str, actual_path: Path) -> dict[str, Any]:
    evidence, alias = "reports/MUTATION_FULL_CATALOGUE_CURRENT.json", "reports/MUTATION_REPORT.json"
    actual, canonical = _object(actual_path), _object(root / evidence)
    if (root / evidence).read_bytes() != (root / alias).read_bytes():
        raise ValueError("canonical mutation aliases differ")
    if (
        not _provenance(actual, source, "scripts/run_mutation_tests.py")
        or not _provenance(canonical, source, "scripts/run_mutation_tests.py")
        or _mutation_projection(actual) != _mutation_projection(canonical)
        or not _mutation_execution_valid(actual)
        or not _mutation_execution_valid(canonical)
    ):
        raise ValueError("hosted mutation execution disagrees with canonical mutation evidence")
    artifacts = [evidence, alias]
    _tracked(root, artifacts)
    return {
        "executor": "mutation",
        "exit_code": 0,
        "result": {
            key: canonical.get(key)
            for key in ("mutants", "killed", "survived", "invalid", "errors", "mutation_score")
        },
        "artifacts": artifacts,
    }


def _inference_execution(
    root: Path, release: str, source: str, actual_path: Path, actual_junit: Path
) -> dict[str, Any]:
    evidence = f"reports/release/{release}/INFERENCE_SECURITY_GATE.json"
    junit_relative = f"reports/release/{release}/INFERENCE_SECURITY_GATE.junit.xml"
    actual, canonical = _object(actual_path), _object(root / evidence)
    actual_counts, canonical_counts = _junit(actual_junit), _junit(root / junit_relative)
    actual_hash = hashlib.sha256(actual_junit.read_bytes()).hexdigest()
    canonical_hash = hashlib.sha256((root / junit_relative).read_bytes()).hexdigest()
    if (
        _inference_projection(actual) != _inference_projection(canonical)
        or actual.get("schema") != "korpus.production-gate.v1"
        or actual.get("gate_id") != "inference_security"
        or actual.get("status") != "PASS"
        or actual.get("release") != release
        or actual.get("source_tree_sha256") != source
        or actual.get("digest_scope") != "evidence_paths"
        or actual.get("pytest") != actual_counts
        or actual.get("junit_sha256") != actual_hash
        or canonical.get("pytest") != canonical_counts
        or canonical.get("junit_sha256") != canonical_hash
        or actual_counts != canonical_counts
    ):
        raise ValueError("hosted inference execution disagrees with canonical inference evidence")
    artifacts = [evidence, junit_relative]
    _tracked(root, artifacts)
    return {
        "executor": "inference",
        "exit_code": 0,
        "result": canonical_counts,
        "artifacts": artifacts,
    }


def _web_execution(
    root: Path, release: str, source: str, actual_path: Path, actual_tap: Path
) -> dict[str, Any]:
    evidence = f"reports/release/{release}/WEB_REGRESSION_REPORT.json"
    tap_relative = f"reports/release/{release}/WEB_REGRESSION_REPORT.tap"
    actual, canonical = _object(actual_path), _object(root / evidence)
    actual_counts, actual_hash = _tap(actual_tap)
    canonical_counts, canonical_hash = _tap(root / tap_relative)
    if (
        not _provenance(actual, source, "scripts/publish_web_regression.py")
        or not _provenance(canonical, source, "scripts/publish_web_regression.py")
        or _stable_web(actual) != _stable_web(canonical)
        or not _web_execution_valid(actual, release, actual_counts, actual_hash)
        or not _web_execution_valid(canonical, release, canonical_counts, canonical_hash)
        or actual_counts != canonical_counts
    ):
        raise ValueError("fresh web execution disagrees with canonical web evidence")
    artifacts = [evidence, tap_relative]
    _tracked(root, artifacts)
    return {
        "executor": "web",
        "exit_code": 0,
        "result": {
            "tests": canonical.get("tests"),
            "pass": canonical.get("passed"),
            "fail": canonical.get("failed"),
            "skipped": canonical.get("skipped"),
        },
        "artifacts": artifacts,
    }


def build(
    root: Path,
    inputs: HostedInputs,
    identity: Mapping[str, Any],
    source_ref: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not canonical_identity(identity):
        raise ValueError("release-claim producer is not canonical GitHub Actions")
    command = ["git", "-C", str(root), "rev-parse", "HEAD"]
    head = subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()
    if identity.get("commit_sha") != head:
        raise ValueError("GitHub execution identity is not the checked-out commit")
    if not allowed_source_ref(source_ref):
        raise ValueError("release-claim producer source ref is not canonical or bootstrap")
    release, source = release_tag(root), compute_source_digest(root)
    executions = {
        "CLM-REGRESSION": _backend_execution(root, release, source, inputs.sqlite_junit),
        "CLM-WEB": _web_execution(root, release, source, inputs.web, inputs.web_tap),
        "CLM-MUTATION": _mutation_execution(root, source, inputs.mutation),
        "CLM-INFERENCE-SECURITY": _inference_execution(
            root, release, source, inputs.inference, inputs.inference_junit
        ),
    }
    attestation = new_attestation(root, release, source, executions, source_ref=source_ref)
    attestation_bytes = (json.dumps(attestation, ensure_ascii=False, indent=2) + "\n").encode()
    subjects = {
        "release-claims": {
            "release": release,
            "source_tree_sha256": source,
            "digest_scope": "evidence_paths",
            "tracked_tree_sha256": attestation["tracked_tree_sha256"],
            "source_ref": source_ref,
            "claims": sorted(CLAIM_EXECUTORS),
        }
    }
    receipt = new_receipt(
        identity,
        kind="release-claims",
        job="release-claims",
        source_tree_sha256=str(attestation["tracked_tree_sha256"]),
        artifacts={ATTESTATION_NAME: attestation_bytes},
        subjects=subjects,
    )
    inputs.out_dir.mkdir(parents=True, exist_ok=True)
    (inputs.out_dir / ATTESTATION_NAME).write_bytes(attestation_bytes)
    (inputs.out_dir / RECEIPT_NAME).write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return attestation, receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-junit", type=Path, required=True)
    parser.add_argument("--mutation", type=Path, required=True)
    parser.add_argument("--inference", type=Path, required=True)
    parser.add_argument("--inference-junit", type=Path, required=True)
    parser.add_argument("--web", type=Path, required=True)
    parser.add_argument("--web-tap", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        attestation, receipt = build(
            ROOT,
            HostedInputs(
                args.sqlite_junit,
                args.mutation,
                args.inference,
                args.inference_junit,
                args.web,
                args.web_tap,
                args.out_dir,
            ),
            identity=identity_from_environment(),
            source_ref=os.environ.get("GITHUB_REF", ""),
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}, ensure_ascii=False))
        return 1
    summary = {
        "status": "PASS",
        "claims": sorted(attestation["claims"]),
        "run_id": receipt["run_id"],
        "run_attempt": receipt["run_attempt"],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
