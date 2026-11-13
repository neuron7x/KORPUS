"""Verify the immutable historical migration chain before admitting its forward path."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

_MIGRATION_PATH = re.compile(r"apps/api/migrations/versions/[a-z0-9_]+\.py\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class BaselineProofError(RuntimeError):
    """The packaged historical migration policy does not prove this source."""


@dataclass(frozen=True)
class BaselineProof:
    chain: tuple[str, ...]
    files: frozenset[str]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate policy key")
        result[key] = value
    return result


def _read_source(root: Path, relative: str) -> bytes:
    path = root / relative
    if any(part.is_symlink() for part in (path, *path.parents) if part != root):
        raise BaselineProofError("DENIED_BASELINE_SOURCE_SYMLINK")
    return path.read_bytes()


def _assignment(tree: ast.Module, name: str) -> str | None:
    values: list[ast.expr | None] = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                values.append(node.value)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            values.append(node.value)
    if len(values) != 1 or not isinstance(values[0], ast.Constant):
        raise BaselineProofError("DENIED_BASELINE_GRAPH_UNPROVEN")
    value = values[0].value
    if value is not None and not isinstance(value, str):
        raise BaselineProofError("DENIED_BASELINE_GRAPH_UNPROVEN")
    return value


def _records(root: Path, records: object) -> tuple[dict[str, str | None], frozenset[str]]:
    if not isinstance(records, dict) or not records:
        raise BaselineProofError("DENIED_BASELINE_POLICY_INVALID")
    revisions: dict[str, str | None] = {}
    paths: set[str] = set()
    for relative, digest in records.items():
        if not isinstance(relative, str) or not _MIGRATION_PATH.fullmatch(relative):
            raise BaselineProofError("DENIED_BASELINE_POLICY_INVALID")
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise BaselineProofError("DENIED_BASELINE_POLICY_INVALID")
        source = _read_source(root, relative)
        if hashlib.sha256(source).hexdigest() != digest:
            raise BaselineProofError("DENIED_BASELINE_SOURCE_CHANGED")
        tree = ast.parse(source, filename=relative)
        revision, down = _assignment(tree, "revision"), _assignment(tree, "down_revision")
        if not revision or revision in revisions:
            raise BaselineProofError("DENIED_BASELINE_GRAPH_UNPROVEN")
        revisions[revision] = down
        paths.add(relative)
    return revisions, frozenset(paths)


def _chain(revisions: dict[str, str | None], head: object) -> tuple[str, ...]:
    if not isinstance(head, str):
        raise BaselineProofError("DENIED_BASELINE_POLICY_INVALID")
    chain: list[str] = []
    current: str | None = head
    while current is not None:
        if current not in revisions or current in chain:
            raise BaselineProofError("DENIED_BASELINE_GRAPH_UNPROVEN")
        chain.append(current)
        current = revisions[current]
    if len(chain) != len(revisions):
        raise BaselineProofError("DENIED_BASELINE_GRAPH_UNPROVEN")
    return tuple(reversed(chain))


def verify_baseline(root: Path) -> BaselineProof:
    """A policy marker alone is insufficient: hash all members and prove one complete chain."""
    try:
        policy = json.loads(
            _read_source(root, "config/production/migration-policy.json"),
            object_pairs_hook=_unique_object,
        )
        if not isinstance(policy, dict):
            raise BaselineProofError("DENIED_BASELINE_POLICY_INVALID")
        revisions, files = _records(root, policy.get("baseline_files"))
        return BaselineProof(_chain(revisions, policy.get("baseline_revision")), files)
    except (OSError, ValueError, SyntaxError) as exc:
        raise BaselineProofError("DENIED_BASELINE_PROOF_UNAVAILABLE") from exc


def proven_baseline_forward(current: tuple[str, ...], target: str, chain: tuple[str, ...]) -> bool:
    return (
        len(current) == 1
        and current[0] in chain
        and target in chain
        and chain.index(current[0]) <= chain.index(target)
    )
