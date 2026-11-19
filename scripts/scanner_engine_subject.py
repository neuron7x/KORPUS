"""Record exact workflow checkout anchors without borrowing admission authority."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from scripts.scanner_engine_result import read_output
from scripts.source_security_contract import require, strict_json


def workflow_subject(before: dict[str, Any]) -> dict[str, Any]:
    run = before["run"]
    require(run["GITHUB_REPOSITORY"] == "neuron7x/KORPUS", "unexpected diagnostic repository")
    event = os.environ.get("GITHUB_EVENT_NAME")
    require(event in {"pull_request", "workflow_dispatch"}, "unexpected diagnostic event")
    reference = os.environ.get("GITHUB_REF", "")
    require(bool(reference) and not any(char.isspace() for char in reference), "invalid event ref")
    result: dict[str, Any] = {
        "event": event,
        "ref": reference,
        "checkout_sha": before["source_commit_sha"],
        "checkout_tree": before["source_tree_oid"],
        "run_id": run["GITHUB_RUN_ID"],
        "run_attempt": run["GITHUB_RUN_ATTEMPT"],
        "metadata_is_independent_attestation": False,
    }
    if event == "pull_request":
        path = Path(os.environ.get("GITHUB_EVENT_PATH", ""))
        require(path.is_absolute() and path.stat().st_size <= 2 * 1024 * 1024, "unsafe event file")
        raw = read_output(path, path.parent)
        value = strict_json(raw)
        result["event_sha256"] = hashlib.sha256(raw).hexdigest()
        require(isinstance(value, dict), "invalid pull request event")
        pull = value.get("pull_request")
        require(isinstance(pull, dict), "missing pull request event subject")
        assert isinstance(pull, dict)
        for side in ("head", "base"):
            edge = pull.get(side)
            require(isinstance(edge, dict), "missing pull request commit edge")
            assert isinstance(edge, dict)
            sha, ref = edge.get("sha"), edge.get("ref")
            require(
                isinstance(sha, str)
                and re.fullmatch(r"[a-f0-9]{40}", sha) is not None
                and isinstance(ref, str)
                and bool(ref),
                "invalid pull request commit edge",
            )
            result[side] = {"sha": sha, "ref": ref}
        require(type(pull.get("number")) is int and pull["number"] > 0, "invalid pull number")
        require(reference == f"refs/pull/{pull['number']}/merge", "pull event ref differs")
        result["pull_number"] = pull["number"]
    else:
        require(reference.startswith(("refs/heads/", "refs/tags/")), "invalid dispatched Git ref")
        result["head"] = {"sha": before["source_commit_sha"], "ref": reference}
    return result


def scanner_policy(root: Path) -> dict[str, Any]:
    baseline = (root / ".gitleaks-baseline.json").read_bytes()
    value = strict_json(baseline)
    require(
        isinstance(value, list) and len(value) == 22, "diagnostic baseline is not the 22 records"
    )
    return {
        "baseline_sha256": hashlib.sha256(baseline).hexdigest(),
        "baseline_records": len(value),
        "config_sha256": hashlib.sha256((root / ".gitleaks.toml").read_bytes()).hexdigest(),
        "native_timeout_seconds": 230,
        "parent_timeout_seconds": 240,
        "cpus": 2,
        "memory": "2g",
        "pids_limit": 256,
        "gomaxprocs": 2,
        "default_max_decode_depth": 5,
        "changed_authoritative_scanner": False,
    }
