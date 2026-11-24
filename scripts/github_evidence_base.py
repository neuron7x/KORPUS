"""Observe the live PR base, prove recorded ancestry and reject admission-time movement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from coverage_execution_contract import canonical_bytes
from github_evidence_policy import API_HOST, API_PREFIX
from github_evidence_transport import GitHubEvidenceError, GitHubTransport, insist, object_record
from korpus.application.github_release_context import GIT_SHA


@dataclass(frozen=True)
class BaseAuthority:
    number: int
    ref: str
    sha: str
    subject_bytes: bytes


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or GIT_SHA.fullmatch(value) is None:
        raise GitHubEvidenceError(f"invalid {label} SHA")
    return value


def _base_tip(api: GitHubTransport, ref: str) -> str:
    record = api.json("/git/ref/heads/" + quote(ref, safe="/"))
    insist(record.get("ref") == f"refs/heads/{ref}", "GitHub base ref changed its subject")
    commit = object_record(record.get("object"), "GitHub base ref has no commit object")
    insist(commit.get("type") == "commit", "GitHub base ref is not a commit")
    return _sha(commit.get("sha"), "live PR base")


def _recorded_ancestor(api: GitHubTransport, recorded: str, current: str) -> None:
    path = f"/compare/{recorded}...{current}"
    # Page two omits changed-file patches; only the bounded ancestry summary is authority.
    comparison = api.json(path + "?per_page=1&page=2")
    insist(
        comparison.get("url") == f"https://{API_HOST}{API_PREFIX}{path}",
        "GitHub base comparison changed its subject",
    )
    base = object_record(comparison.get("base_commit"), "comparison base commit is missing")
    merge = object_record(comparison.get("merge_base_commit"), "comparison merge base is missing")
    insist(
        base.get("sha") == merge.get("sha") == recorded,
        "recorded PR base is not the current base ancestor",
    )
    ahead, behind, total = (
        comparison.get(name) for name in ("ahead_by", "behind_by", "total_commits")
    )
    insist(
        comparison.get("status") == "ahead"
        and type(ahead) is int
        and ahead > 0
        and type(behind) is int
        and behind == 0
        and type(total) is int
        and total == ahead,
        "recorded PR base ancestry is not an exact forward comparison",
    )


def _edge(value: Any) -> dict[str, Any]:
    edge = object_record(value, "PR subject edge is missing")
    repository = object_record(edge.get("repo"), "PR subject repository is missing")
    owner = object_record(repository.get("owner"), "PR subject owner is missing")
    return {
        "sha": edge.get("sha"),
        "ref": edge.get("ref"),
        "repository_id": repository.get("id"),
        "repository_name": repository.get("full_name"),
        "owner_id": owner.get("id"),
        "owner_name": owner.get("login"),
    }


def _subject(pull: dict[str, Any]) -> bytes:
    return canonical_bytes(
        {
            "number": pull.get("number"),
            "merge_commit_sha": pull.get("merge_commit_sha"),
            "head": _edge(pull.get("head")),
            "base": _edge(pull.get("base")),
        }
    )


def observe_pr_base(api: GitHubTransport, pull: dict[str, Any]) -> BaseAuthority:
    base = object_record(pull.get("base"), "PR base metadata missing")
    recorded = _sha(base.get("sha"), "recorded PR base")
    ref = base.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        raise GitHubEvidenceError("PR base branch is missing")
    current = _base_tip(api, ref)
    if recorded != current:
        _recorded_ancestor(api, recorded, current)
    return BaseAuthority(pull["number"], ref, current, _subject(pull))


def stable_pr_base(api: GitHubTransport, authority: BaseAuthority) -> None:
    pull = api.json(f"/pulls/{authority.number}")
    insist(_subject(pull) == authority.subject_bytes, "PR subject changed during run admission")
    insist(
        _base_tip(api, authority.ref) == authority.sha,
        "PR base ref changed during run admission",
    )
