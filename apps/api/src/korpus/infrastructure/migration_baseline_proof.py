"""Verify the immutable historical migration chain before admitting its forward path."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from alembic.script.base import Script

_MIGRATION_PATH = re.compile(r"apps/api/migrations/versions/[a-z0-9_]+\.py\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class BaselineProofError(RuntimeError):
    """The packaged historical migration policy does not prove this source."""


@dataclass(frozen=True)
class RevisionSource:
    path: str
    revision: str
    source: bytes


@dataclass(frozen=True)
class BaselineProof:
    chain: tuple[str, ...]
    files: frozenset[str]
    sources: tuple[RevisionSource, ...]


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


def _records(
    root: Path, records: object
) -> tuple[dict[str, str | None], tuple[RevisionSource, ...]]:
    if not isinstance(records, dict) or not records:
        raise BaselineProofError("DENIED_BASELINE_POLICY_INVALID")
    revisions: dict[str, str | None] = {}
    sources: list[RevisionSource] = []
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
        sources.append(RevisionSource(relative, revision, source))
    return revisions, tuple(sources)


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
        revisions, sources = _records(root, policy.get("baseline_files"))
        return BaselineProof(
            _chain(revisions, policy.get("baseline_revision")),
            frozenset(item.path for item in sources),
            sources,
        )
    except (OSError, ValueError, SyntaxError) as exc:
        raise BaselineProofError("DENIED_BASELINE_PROOF_UNAVAILABLE") from exc


def proven_baseline_forward(current: tuple[str, ...], target: str, chain: tuple[str, ...]) -> bool:
    return (
        len(current) == 1
        and current[0] in chain
        and target in chain
        and chain.index(current[0]) <= chain.index(target)
    )


def _passive_annotation(node: ast.expr | None) -> bool:
    if isinstance(node, ast.Name):
        return node.id in {"str", "Sequence"}
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _passive_annotation(node.left) and _passive_annotation(node.right)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        return node.value.id == "Sequence" and _passive_annotation(node.slice)
    return node is None


def _passive_binding(node: ast.stmt) -> str:
    """A deliberately narrow grammar, not a general Python side-effect detector."""
    if isinstance(node, ast.FunctionDef):
        args = node.args
        if (
            not node.decorator_list
            and not node.type_params
            and not (args.posonlyargs or args.args or args.kwonlyargs or args.vararg or args.kwarg)
            and not args.defaults
            and not args.kw_defaults
            and _passive_annotation(node.returns)
        ):
            return node.name
    elif isinstance(node, ast.AnnAssign):
        if (
            isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and _passive_annotation(node.annotation)
        ):
            return node.target.id
    elif isinstance(node, ast.Assign):
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
        ):
            return node.targets[0].id
    raise BaselineProofError("DENIED_REVISION_INITIALIZATION_UNPROVEN")


def verify_passive_revision(root: Path, revision: str, parent: str) -> RevisionSource:
    """Prove metadata and passive initialization without importing revision Python."""
    path = f"apps/api/migrations/versions/{revision}.py"
    source = _read_source(root, path)
    tree = ast.parse(source, filename=path)
    allowed_imports = {
        ("__future__", "annotations"),
        ("collections.abc", "Sequence"),
        ("alembic", "op"),
    }
    imports: set[tuple[str | None, str]] = set()
    bindings: set[str] = set()
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        if isinstance(node, ast.ImportFrom) and node.level == 0 and len(node.names) == 1:
            item = node.names[0]
            key = (node.module, item.name)
            if (
                key in allowed_imports
                and key not in imports
                and item.name not in bindings
                and item.asname is None
            ):
                imports.add(key)
                bindings.add(item.name)
                continue
        name = _passive_binding(node)
        if name.startswith("__") or name in bindings:
            raise BaselineProofError("DENIED_REVISION_INITIALIZATION_UNPROVEN")
        bindings.add(name)
    if imports != allowed_imports:
        raise BaselineProofError("DENIED_REVISION_INITIALIZATION_UNPROVEN")
    expected = {
        "revision": revision,
        "down_revision": parent,
        "branch_labels": None,
        "depends_on": None,
    }
    if any(_assignment(tree, name) != value for name, value in expected.items()):
        raise BaselineProofError("DENIED_REVISION_GRAPH_UNPROVEN")
    return RevisionSource(path, revision, source)


def load_proven_revisions(root: Path, sources: tuple[RevisionSource, ...]) -> Iterator[Script]:
    """Execute only captured source bytes, after admission; never load cached bytecode."""
    for item in sources:
        path = str(root / item.path)
        module = ModuleType(Path(item.path).stem)
        module.__file__ = path
        exec(compile(item.source, path, "exec", dont_inherit=True), module.__dict__)
        yield Script(module, item.revision, path)
