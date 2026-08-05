"""The revision the code expects must be the head the migrations produce.

`SqlRepository.initialize(create_schema=False)` — the production path — refuses to
start unless `alembic_version` equals `SCHEMA_REVISION`. Migration 0010 shipped and the
constant stayed at 0009, so a fully migrated PostgreSQL database raised
`database schema revision mismatch: expected 0009_reviewer_credentials, got
0010_revision_identity` on start-up. Reproduced on 2026-08-04 against
pgvector/pgvector:0.8.5-pg17 with the migrations applied from scratch.

Nothing caught it: the tests run on SQLite with `create_schema=True`, which builds the
tables from metadata and never reads `alembic_version`, and the constant had no test of
its own. The head is therefore computed here from the migration graph — the same files
alembic walks — so the next migration cannot ship without moving the pin.
"""

from __future__ import annotations

import ast
from pathlib import Path

from korpus.infrastructure.repository import SCHEMA_REVISION

VERSIONS = Path("apps/api/migrations/versions")


def _revision_graph() -> tuple[dict[str, str | None], set[str]]:
    """Map revision -> down_revision, read statically rather than by import.

    Importing the modules would execute alembic's `op` bindings; parsing keeps the
    check runnable in the same place the pipeline runs it.
    """

    graph: dict[str, str | None] = {}
    for path in sorted(VERSIONS.glob("[0-9]*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assignments: dict[str, str | None] = {}
        for node in tree.body:
            if not isinstance(node, ast.AnnAssign | ast.Assign):
                continue
            targets = (
                [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
            )
            names = [target.id for target in targets if isinstance(target, ast.Name)]
            if not names or node.value is None:
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str | type(None)):
                for name in names:
                    assignments[name] = value.value
        if "revision" in assignments and assignments["revision"] is not None:
            graph[assignments["revision"]] = assignments.get("down_revision")
    return graph, {value for value in graph.values() if value is not None}


def test_the_migration_graph_has_exactly_one_head() -> None:
    graph, parents = _revision_graph()

    heads = sorted(set(graph) - parents)

    assert len(heads) == 1, f"expected one migration head, found {heads}"


def test_the_code_pins_the_head_of_the_migration_graph() -> None:
    graph, parents = _revision_graph()
    head = next(iter(set(graph) - parents))

    assert head == SCHEMA_REVISION, (
        f"SCHEMA_REVISION is {SCHEMA_REVISION!r} but the migrations end at {head!r}: "
        "a migrated database would refuse to start"
    )


def test_every_revision_except_the_first_has_a_parent_that_exists() -> None:
    """A dangling parent makes `upgrade head` fail only once someone runs it."""
    graph, _parents = _revision_graph()

    dangling = {
        revision: parent
        for revision, parent in graph.items()
        if parent is not None and parent not in graph
    }

    assert dangling == {}, dangling
