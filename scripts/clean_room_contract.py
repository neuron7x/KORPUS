from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from xml.etree import ElementTree

from trusted_system_tools import git_executable, ssh_keygen_executable

try:
    from .evidence_source_binding import committed_evidence_source_digest
    from .release_identity import release_tag
except ImportError:  # direct script execution with scripts/ on sys.path
    from evidence_source_binding import committed_evidence_source_digest
    from release_identity import release_tag

JUNIT = "reports/closure/CLEAN_ROOM_REPRODUCTION.junit.xml"
REPORT = "reports/closure/CLEAN_ROOM_REPRODUCTION.json"
SIGNATURE = f"{REPORT}.sig"
ALLOWED_SIGNERS = "config/operations/trusted-git-signers"
LOCK = "apps/api/requirements.dev.lock"
SHA1 = re.compile(r"[0-9a-f]{40}")


def junit_counts(path: Path) -> dict[str, int]:
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    total = sum(int(suite.get("tests", "0")) for suite in suites)
    skipped = sum(int(suite.get("skipped", "0")) for suite in suites)
    return {
        "tests": total - skipped,
        "failures": sum(int(suite.get("failures", "0")) for suite in suites),
        "errors": sum(int(suite.get("errors", "0")) for suite in suites),
        "skipped": skipped,
    }


def _git_bytes(root: Path, ref: str, path: str) -> bytes | None:
    git = git_executable()
    if git is None:
        return None
    completed = subprocess.run(
        [git, "show", f"{ref}:{path}"], cwd=root, check=False, capture_output=True
    )
    return completed.stdout if completed.returncode == 0 else None


def _candidate_bound(root: Path, candidate: object, digest: str) -> bool:
    if not isinstance(candidate, str) or SHA1.fullmatch(candidate) is None:
        return False
    try:
        observed: str = committed_evidence_source_digest(candidate, root)
        return observed == digest
    except RuntimeError:
        return False


def _lock_bound(root: Path, candidate: object, expected: object) -> bool:
    if not isinstance(candidate, str) or not isinstance(expected, str):
        return False
    payload = _git_bytes(root, candidate, LOCK)
    return payload is not None and hashlib.sha256(payload).hexdigest() == expected


def _trunk_urls(root: Path) -> set[str]:
    try:
        payload = json.loads((root / "config/operations/forges.json").read_text(encoding="utf-8"))
        trunk = payload["forges"]["trunk"]
        return {str(trunk["url"]), str(trunk["ssh"])}
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return set()


def _candidate_on_live_remote(root: Path, candidate: object, remote: object) -> bool:
    if not isinstance(candidate, str) or not isinstance(remote, str):
        return False
    try:
        state = json.loads(
            (root / "config/operations/canonical-state.json").read_text(encoding="utf-8")
        )
        branch = state["canonical_branch"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return False
    if not isinstance(branch, str) or not branch:
        return False
    git = git_executable()
    if git is None:
        return False
    completed = subprocess.run(
        [git, "ls-remote", remote, f"refs/heads/{branch}"],
        check=False,
        capture_output=True,
        text=True,
    )
    lines = [line.split() for line in completed.stdout.splitlines()]
    return completed.returncode == 0 and lines == [[candidate, f"refs/heads/{branch}"]]


def _trust_root_bound(root: Path, candidate: object) -> bool:
    if not isinstance(candidate, str):
        return False
    committed = _git_bytes(root, candidate, ALLOWED_SIGNERS)
    path = root / ALLOWED_SIGNERS
    return committed is not None and path.is_file() and committed == path.read_bytes()


def _owner_attestation(root: Path, payload: Mapping[str, object]) -> bool:
    signer = payload.get("attested_by")
    if not isinstance(signer, str) or payload.get("attestation_class") != "OWNER_ATTESTED":
        return False
    report, signature = root / REPORT, root / SIGNATURE
    allowed = root / ALLOWED_SIGNERS
    if (
        not report.is_file()
        or not signature.is_file()
        or not allowed.is_file()
        or not _trust_root_bound(root, payload.get("candidate_sha"))
    ):
        return False
    ssh_keygen = ssh_keygen_executable()
    if ssh_keygen is None:
        return False
    completed = subprocess.run(
        [
            ssh_keygen,
            "-Y",
            "verify",
            "-f",
            str(allowed),
            "-I",
            signer,
            "-n",
            "korpus-clean-room",
            "-s",
            str(signature),
        ],
        input=report.read_bytes(),
        check=False,
        capture_output=True,
    )
    return completed.returncode == 0


def clean_room_contract(root: Path, payload: Mapping[str, object], digest: str) -> dict[str, bool]:
    candidate = payload.get("candidate_sha")
    junit_path = root / JUNIT
    try:
        observed_counts = junit_counts(junit_path)
    except (OSError, ValueError, ElementTree.ParseError):
        observed_counts = None
    recorded_counts = payload.get("pytest")
    junit_hash = (
        hashlib.sha256(junit_path.read_bytes()).hexdigest() if junit_path.is_file() else None
    )
    run_clean = (
        observed_counts is not None
        and observed_counts["tests"] > 0
        and observed_counts["failures"] == observed_counts["errors"] == 0
        and payload.get("pytest_exit_code") == 0
    )
    return {
        "schema_exact": payload.get("schema") == "korpus.clean-room-remote.v1",
        "class_is_remote": payload.get("class") == "REMOTE_SOURCE_FRESH_DEPENDENCIES",
        "producer_exact": payload.get("produced_by") == "scripts/reproduce_clean_room.py",
        "remote_is_trunk": payload.get("remote") in _trunk_urls(root)
        and payload.get("remote_class") == "TRUNK",
        "candidate_on_live_trunk": _candidate_on_live_remote(
            root, candidate, payload.get("remote")
        ),
        "release_bound": payload.get("release") == release_tag(root),
        "source_bound": bool(digest) and payload.get("source_tree_sha256") == digest,
        "scope_exact": payload.get("digest_scope") == "evidence_paths",
        "candidate_source_bound": _candidate_bound(root, candidate, digest),
        "dependency_lock_bound": _lock_bound(
            root, candidate, payload.get("dependency_freeze_sha256")
        ),
        "junit_present": payload.get("junit_path") == JUNIT and junit_path.is_file(),
        "junit_hash_bound": payload.get("junit_sha256") == junit_hash,
        "junit_counts_match": isinstance(recorded_counts, dict)
        and recorded_counts == observed_counts,
        "trust_root_candidate_bound": _trust_root_bound(root, candidate),
        "owner_attestation_verified": _owner_attestation(root, payload),
        "run_counted": observed_counts is not None and observed_counts["tests"] > 0,
        "run_clean": run_clean,
        "status_coherent": payload.get("status") == ("PASS" if run_clean else "FAIL"),
        "status_pass": payload.get("status") == "PASS",
    }
