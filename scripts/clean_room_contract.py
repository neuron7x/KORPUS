from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from korpus.application.provenance import (
    EVIDENCE_SOURCE_PATHS,
    digest_source_records,
    evidence_source_path_included,
)
from trusted_system_tools import git_executable, ssh_keygen_executable

try:
    from .clean_room_collection_contract import collection_checks
    from .release_identity import release_tag
except ImportError:  # direct script execution with scripts/ on sys.path
    from clean_room_collection_contract import collection_checks
    from release_identity import release_tag

JUNIT = "reports/closure/CLEAN_ROOM_REPRODUCTION.junit.xml"
MIRROR_JUNIT = "reports/closure/CLEAN_ROOM_REPRODUCTION.mirror.junit.xml"
REPORT = "reports/closure/CLEAN_ROOM_REPRODUCTION.json"
SIGNATURE = f"{REPORT}.sig"
ALLOWED_SIGNERS = "config/operations/trusted-git-signers"
LOCK = "apps/api/requirements.dev.lock"
SHA1 = re.compile(r"[0-9a-f]{40}")
CORE_PUBLISHED_EVIDENCE = frozenset({REPORT, JUNIT, SIGNATURE})
PUBLISHED_EVIDENCE = CORE_PUBLISHED_EVIDENCE | {MIRROR_JUNIT}


@dataclass(frozen=True)
class RemoteObservation:
    candidate_digest: str
    live_digest: str
    dependency_lock: bytes | None
    trust_root: bytes | None
    candidate_on_live_trunk: bool


def isolated_git_environment(home: Path) -> dict[str, str]:
    """Git observation without ambient URL rewrites, repository config or Git env."""
    home.mkdir(parents=True, exist_ok=True)
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "xdg"),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }


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


def _git(root: Path, env: Mapping[str, str], *args: str) -> subprocess.CompletedProcess[bytes]:
    git = git_executable()
    if git is None:
        raise OSError("trusted git executable is unavailable")
    return subprocess.run(
        [git, "-C", str(root), *args], check=False, capture_output=True, env=dict(env)
    )


def _git_bytes(root: Path, env: Mapping[str, str], ref: str, path: str) -> bytes | None:
    completed = _git(root, env, "show", f"{ref}:{path}")
    return completed.stdout if completed.returncode == 0 else None


def _commit_digest(root: Path, env: Mapping[str, str], ref: str) -> str | None:
    listing = _git(
        root,
        env,
        "ls-tree",
        "-r",
        "-z",
        "--name-only",
        ref,
        "--",
        *EVIDENCE_SOURCE_PATHS,
    )
    if listing.returncode:
        return None
    names = sorted(
        {
            raw.decode("utf-8")
            for raw in listing.stdout.split(b"\0")
            if raw and evidence_source_path_included(raw.decode("utf-8"))
        }
    )
    records: list[tuple[str, bytes]] = []
    for name in names:
        content = _git_bytes(root, env, ref, name)
        if content is None:
            return None
        records.append((name, content))
    return str(digest_source_records(records))


def _canonical_branch(root: Path) -> str | None:
    try:
        state = json.loads(
            (root / "config/operations/canonical-state.json").read_text(encoding="utf-8")
        )
        branch = state["canonical_branch"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(branch, str) or not branch:
        return None
    return str(branch)


def _changed_paths(
    repository: Path, env: Mapping[str, str], candidate: str, live: str
) -> frozenset[str] | None:
    diff = _git(
        repository,
        env,
        "diff",
        "--name-only",
        "--no-renames",
        "-z",
        candidate,
        live,
        "--",
    )
    if diff.returncode:
        return None
    return frozenset(raw.decode("utf-8") for raw in diff.stdout.split(b"\0") if raw)


def _published_evidence_matches(
    root: Path,
    repository: Path,
    env: Mapping[str, str],
    live: str,
    changed: frozenset[str],
) -> bool:
    compared = CORE_PUBLISHED_EVIDENCE | changed
    return all(
        (root / path).is_file()
        and _git_bytes(repository, env, live, path) == (root / path).read_bytes()
        for path in compared
    )


def _trunk_urls(root: Path) -> set[str]:
    try:
        payload = json.loads((root / "config/operations/forges.json").read_text(encoding="utf-8"))
        trunk = payload["forges"]["trunk"]
        return {str(trunk["url"]), str(trunk["ssh"])}
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return set()


def _clone_live_branch(
    base: Path, remote: str, branch: str
) -> tuple[Path, dict[str, str], str] | None:
    git = git_executable()
    if git is None:
        return None
    repository = base / "remote.git"
    env = isolated_git_environment(base / "home")
    clone = subprocess.run(
        [
            git,
            "clone",
            "--bare",
            "--quiet",
            "--single-branch",
            "--branch",
            branch,
            "--no-tags",
            "--",
            remote,
            str(repository),
        ],
        check=False,
        capture_output=True,
        env=env,
    )
    if clone.returncode:
        return None
    live = _git(repository, env, "rev-parse", "--verify", f"refs/heads/{branch}")
    if live.returncode:
        return None
    return repository, env, live.stdout.decode("ascii").strip()


def _remote_observation(root: Path, candidate: object, remote: object) -> RemoteObservation | None:
    if not isinstance(candidate, str) or not isinstance(remote, str):
        return None
    if SHA1.fullmatch(candidate) is None:
        return None
    branch = _canonical_branch(root)
    if branch is None:
        return None
    try:
        with TemporaryDirectory(prefix="korpus-clean-room-remote-") as temporary:
            base = Path(temporary)
            cloned = _clone_live_branch(base, remote, branch)
            if cloned is None:
                return None
            repository, env, live = cloned
            candidate_digest = _commit_digest(repository, env, candidate)
            live_digest = _commit_digest(repository, env, live)
            if candidate_digest is None or live_digest is None:
                return None
            ancestor = _git(repository, env, "merge-base", "--is-ancestor", candidate, live)
            paths = _changed_paths(repository, env, candidate, live)
            evidence_descendant = (
                live != candidate
                and ancestor.returncode == 0
                and paths is not None
                and bool(paths)
                and paths <= PUBLISHED_EVIDENCE
                and candidate_digest == live_digest
                and _published_evidence_matches(root, repository, env, live, paths)
            )
            return RemoteObservation(
                candidate_digest=candidate_digest,
                live_digest=live_digest,
                dependency_lock=_git_bytes(repository, env, candidate, LOCK),
                trust_root=_git_bytes(repository, env, candidate, ALLOWED_SIGNERS),
                candidate_on_live_trunk=live == candidate or evidence_descendant,
            )
    except (OSError, UnicodeError, ValueError):
        return None


def _candidate_on_live_remote(root: Path, candidate: object, remote: object) -> bool:
    observation = _remote_observation(root, candidate, remote)
    return observation is not None and observation.candidate_on_live_trunk


def _candidate_bound(observation: RemoteObservation | None, digest: str) -> bool:
    return observation is not None and bool(digest) and observation.candidate_digest == digest


def _lock_bound(observation: RemoteObservation | None, expected: object) -> bool:
    return (
        observation is not None
        and observation.dependency_lock is not None
        and isinstance(expected, str)
        and hashlib.sha256(observation.dependency_lock).hexdigest() == expected
    )


def _trust_root_bound(root: Path, observation: RemoteObservation | None) -> bool:
    path = root / ALLOWED_SIGNERS
    return (
        observation is not None
        and observation.trust_root is not None
        and path.is_file()
        and observation.trust_root == path.read_bytes()
    )


def _owner_attestation(
    root: Path, payload: Mapping[str, object], trust_root_candidate_bound: bool
) -> bool:
    signer = payload.get("attested_by")
    if not isinstance(signer, str) or payload.get("attestation_class") != "OWNER_ATTESTED":
        return False
    report, signature = root / REPORT, root / SIGNATURE
    allowed = root / ALLOWED_SIGNERS
    if (
        not report.is_file()
        or not signature.is_file()
        or not allowed.is_file()
        or not trust_root_candidate_bound
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
    remote = payload.get("remote")
    remote_is_trunk = remote in _trunk_urls(root) and payload.get("remote_class") == "TRUNK"
    observation = _remote_observation(root, candidate, remote) if remote_is_trunk else None
    trust_root_candidate_bound = _trust_root_bound(root, observation)
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
        "schema_exact": payload.get("schema") == "korpus.clean-room-remote.v2",
        "class_is_remote": payload.get("class") == "REMOTE_SOURCE_FRESH_DEPENDENCIES",
        "producer_exact": payload.get("produced_by") == "scripts/reproduce_clean_room.py",
        "remote_is_trunk": remote_is_trunk,
        "candidate_on_live_trunk": observation is not None and observation.candidate_on_live_trunk,
        "release_bound": payload.get("release") == release_tag(root),
        "source_bound": bool(digest) and payload.get("source_tree_sha256") == digest,
        "scope_exact": payload.get("digest_scope") == "evidence_paths",
        "candidate_source_bound": _candidate_bound(observation, digest),
        "dependency_lock_bound": _lock_bound(observation, payload.get("dependency_freeze_sha256")),
        "junit_present": payload.get("junit_path") == JUNIT and junit_path.is_file(),
        "junit_hash_bound": payload.get("junit_sha256") == junit_hash,
        "junit_counts_match": isinstance(recorded_counts, dict)
        and recorded_counts == observed_counts,
        "trust_root_candidate_bound": trust_root_candidate_bound,
        "owner_attestation_verified": _owner_attestation(root, payload, trust_root_candidate_bound),
        "run_counted": observed_counts is not None and observed_counts["tests"] > 0,
        "run_clean": run_clean,
        "status_coherent": payload.get("status") == ("PASS" if run_clean else "FAIL"),
        "status_pass": payload.get("status") == "PASS",
        **collection_checks(payload, observed_counts),
    }
