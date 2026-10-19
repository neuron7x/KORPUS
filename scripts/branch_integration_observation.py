"""Fail-closed observations for the canonical branch-integration gate."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from branch_integration_declaration import integration_remotes as integration_remotes
from trusted_system_tools import git_executable

ROOT = Path(__file__).resolve().parent.parent
HEAD_SHA = re.compile(r"[0-9a-f]{40}")
TRUSTED_GIT_SIGNERS = "config/operations/trusted-git-signers"
SIGNATURE = re.compile(
    r'Good "git" signature for (?P<signer>\S+) with \S+ key (?P<fingerprint>SHA256:\S+)'
)


def _git(*args: str, root: Path = ROOT) -> str | None:
    git = git_executable()
    if git is None:
        return None
    done = subprocess.run(
        [git, "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() if done.returncode == 0 else None


git_output = _git


def _local_heads(root: Path) -> dict[str, str] | None:
    listed = _git(
        "for-each-ref", "--format=%(refname:short)%09%(objectname)", "refs/heads", root=root
    )
    if listed is None:
        return None
    heads: dict[str, str] = {}
    for line in listed.splitlines():
        name, separator, head = line.partition("\t")
        if not separator or not name or HEAD_SHA.fullmatch(head) is None or name in heads:
            return None
        heads[name] = head
    return heads


def _remote_heads(remote: str, url: str, root: Path) -> dict[str, str] | None:
    """Read the remote itself; remote-tracking refs can be arbitrarily stale."""
    listed = _git("ls-remote", "--heads", "--refs", url, root=root)
    if listed is None:
        return None
    heads: dict[str, str] = {}
    prefix = "refs/heads/"
    for line in listed.splitlines():
        head, separator, full = line.partition("\t")
        if not separator or HEAD_SHA.fullmatch(head) is None or not full.startswith(prefix):
            return None
        branch = full.removeprefix(prefix)
        name = f"{remote}/{branch}"
        if not branch or name in heads:
            return None
        heads[name] = head
    return heads


def refs(root: Path = ROOT, remotes: dict[str, str] | None = None) -> dict[str, str] | None:
    """Return exact local heads plus live remote heads, never cached tracking refs."""
    if not remotes:
        return None
    heads = _local_heads(root)
    if heads is None:
        return None
    for remote, url in sorted(remotes.items()):
        remote_heads = _remote_heads(remote, url, root)
        if not remote_heads or set(heads) & set(remote_heads):
            return None
        heads.update(remote_heads)
    return dict(sorted(heads.items()))


def active_worktree_branches(root: Path = ROOT) -> set[str] | None:
    listed = _git("worktree", "list", "--porcelain", root=root)
    if listed is None:
        return None
    prefix = "branch refs/heads/"
    return {line.removeprefix(prefix) for line in listed.splitlines() if line.startswith(prefix)}


def candidate_branch_head(root: Path = ROOT) -> tuple[str, str] | None:
    branch = _git("symbolic-ref", "--quiet", "--short", "HEAD", root=root)
    if not branch and os.environ.get("GITHUB_ACTIONS") == "true":
        branch = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME")
    head = _git("rev-parse", "HEAD", root=root)
    return (branch, head) if branch and head and HEAD_SHA.fullmatch(head) else None


def unique_commits(canonical: str, head: str, root: Path = ROOT) -> int:
    count = _git("rev-list", "--count", f"{canonical}..{head}", root=root)
    try:
        return int(count if count is not None else "")
    except ValueError as error:
        raise RuntimeError(f"cannot count commits for {head}") from error


def merges_cleanly(canonical: str, head: str, root: Path = ROOT) -> bool:
    git = git_executable()
    if git is None:
        raise RuntimeError("trusted git is unavailable")
    done = subprocess.run(
        [git, "-C", str(root), "merge-tree", "--write-tree", "--name-only", canonical, head],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode not in (0, 1):
        raise RuntimeError(f"cannot test merge for {head}")
    return done.returncode == 0


def is_ancestor(ancestor: str, descendant: str = "HEAD", root: Path = ROOT) -> bool:
    git = git_executable()
    if git is None:
        raise RuntimeError("trusted git is unavailable")
    done = subprocess.run(
        [git, "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode not in (0, 1):
        raise RuntimeError(f"cannot test ancestry for {ancestor}")
    return done.returncode == 0


def archive_tag_verified(tag: str, expected: tuple[str, str], root: Path = ROOT) -> bool:
    trusted = root / TRUSTED_GIT_SIGNERS
    if not trusted.is_file():
        return False
    git = git_executable()
    if git is None:
        return False
    done = subprocess.run(
        [
            git,
            "-C",
            str(root),
            "-c",
            "gpg.format=ssh",
            "-c",
            f"gpg.ssh.allowedSignersFile={trusted}",
            "verify-tag",
            "--raw",
            tag,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    match = SIGNATURE.fullmatch((done.stdout + done.stderr).strip())
    return done.returncode == 0 and match is not None and match.groups() == expected


def remote_tag_state(remote: str, tag: str, root: Path) -> tuple[str, str] | None:
    tag_ref = f"refs/tags/{tag}"
    peeled_ref = f"{tag_ref}^{{}}"
    listed = _git("ls-remote", "--tags", remote, tag_ref, peeled_ref, root=root)
    if listed is None:
        return None
    records: dict[str, str] = {}
    for line in listed.splitlines():
        head, separator, ref = line.partition("\t")
        if not separator or HEAD_SHA.fullmatch(head) is None or ref in records:
            return None
        records[ref] = head
    if set(records) != {tag_ref, peeled_ref}:
        return None
    return records[tag_ref], records[peeled_ref]


def archive_observation(
    entry: dict[str, Any], root: Path, remotes: dict[str, str]
) -> dict[str, Any]:
    tag = entry.get("archive_tag")
    signer = entry.get("archive_signer")
    fingerprint = entry.get("archive_signer_fingerprint")
    branch = entry.get("branch")
    if not (
        isinstance(tag, str)
        and isinstance(signer, str)
        and isinstance(fingerprint, str)
        and isinstance(branch, str)
        and "/" in branch
    ):
        return {"archive_tag_target": None, "archive_tag_verified": False}
    local_object = _git("rev-parse", "--verify", f"refs/tags/{tag}^{{tag}}", root=root)
    remote_state = remote_tag_state(remotes.get(branch.split("/", 1)[0], ""), tag, root)
    return {
        "archive_tag": tag,
        "archive_tag_object": local_object,
        "archive_tag_target": _git(
            "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}", root=root
        ),
        "archive_remote_tag_object": remote_state[0] if remote_state else None,
        "archive_remote_tag_target": remote_state[1] if remote_state else None,
        "archive_tag_verified": archive_tag_verified(tag, (signer, fingerprint), root),
    }


def integrated_observation(
    registry: dict[str, Any], root: Path, remotes: dict[str, str]
) -> dict[str, Any] | None:
    entries = registry.get("integrated")
    if not isinstance(entries, list):
        return None
    observed: dict[str, Any] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        branch, head = entry.get("branch"), entry.get("head")
        if not isinstance(branch, str) or not isinstance(head, str):
            continue
        commit_exists = _git("cat-file", "-e", f"{head}^{{commit}}", root=root) is not None
        state = {
            "head": head,
            "commit_exists": commit_exists,
            "ancestor_of_checkout": is_ancestor(head, root=root) if commit_exists else False,
        }
        if entry.get("disposition") == "superseded_archive":
            state.update(archive_observation(entry, root, remotes))
        observed[branch] = state
    return observed


def _unknown_observation(canonical: str, remotes: dict[str, str] | None) -> dict[str, Any]:
    return {
        "canonical": canonical,
        "active_worktree_branches": None,
        "integration_remotes": dict(sorted(remotes.items())) if remotes else None,
        "diverged": None,
        "integrated": None,
    }


def _active_ref(branch: str, head: str, active_heads: dict[str, str | None]) -> bool:
    if branch in active_heads:
        return True
    _, separator, local = branch.partition("/")
    return bool(separator and active_heads.get(local) == head)


def _diverged_heads(
    canonical: str,
    heads: tuple[dict[str, str], dict[str, str | None]],
    root: Path,
) -> dict[str, Any]:
    candidates, active_heads = heads
    diverged: dict[str, Any] = {}
    for branch, head in candidates.items():
        if branch == canonical or _active_ref(branch, head, active_heads):
            continue
        count = unique_commits(canonical, head, root)
        if count:
            diverged[branch] = {
                "head": head,
                "unique": count,
                "clean": merges_cleanly(canonical, head, root),
            }
    return diverged


def observe(
    canonical: str, root: Path = ROOT, registry: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Measure every inactive local branch and every live integration head."""
    active = active_worktree_branches(root)
    candidate = candidate_branch_head(root)
    remotes = integration_remotes(root)
    candidates = refs(root, remotes)
    if active is None or candidate is None or remotes is None or candidates is None:
        return _unknown_observation(canonical, remotes)
    active_heads = {candidate[0]: candidate[1]}
    return {
        "canonical": canonical,
        "active_worktree_branches": sorted(active),
        "integration_remotes": dict(sorted(remotes.items())),
        "diverged": _diverged_heads(canonical, (candidates, active_heads), root),
        "integrated": integrated_observation(registry or {}, root, remotes),
    }
