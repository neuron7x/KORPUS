"""The grant list and the schema are two statements about the same thing.

`prepare_postgres_role.py` starts from `REVOKE ALL ON ALL TABLES` and then grants,
table by table, from three hand-maintained tuples. That is the right shape — an
omission fails closed rather than opening something up — but it only works while the
tuples keep pace with the migrations.

They did not. `document_compartments` (migration 0004) and `ingestion_jobs` (0005)
were never added, and nothing noticed: the SQLite configuration everything is tested
on has no roles, and the PostgreSQL job had never got past migration 0001, so the
first pipeline that reached it died with
`InsufficientPrivilege: permission denied for table document_compartments`.

This test compares the grant lists against the SQLAlchemy metadata — the same source
the migrations are checked against — so a new table has to be classified before it
can ship.
"""

from __future__ import annotations

import ast
from pathlib import Path

import korpus.infrastructure.ingestion_jobs  # noqa: F401  (registers its table)
from korpus.infrastructure.repository import metadata

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/prepare_postgres_role.py"

# Created and owned by alembic, granted SELECT explicitly at the end of the script.
NOT_APPLICATION_TABLES = {"alembic_version"}


def _grant_lists() -> dict[str, set[str]]:
    """Read the three module-level tuples without importing the script.

    Importing it would need SQLAlchemy plus the environment variables it reads at
    module scope; the question here is purely what the source declares.
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    lists: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.endswith("_TABLES"):
            continue
        lists[target.id] = {
            element.value
            for element in getattr(node.value, "elts", [])
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
    return lists


def test_every_application_table_is_granted_to_the_application_role() -> None:
    lists = _grant_lists()
    assert lists, "the grant tuples are no longer literals — this test cannot read them"
    granted = set().union(*lists.values())
    expected = set(metadata.tables) - NOT_APPLICATION_TABLES
    missing = sorted(expected - granted)
    assert not missing, (
        "these tables exist in the schema but appear in no grant list, so the "
        f"application role is denied access to them at runtime: {missing}"
    )


def test_no_grant_names_a_table_that_does_not_exist() -> None:
    """The mirror image: a stale name means a grant that silently does nothing."""
    lists = _grant_lists()
    granted = set().union(*lists.values())
    unknown = sorted(granted - set(metadata.tables) - NOT_APPLICATION_TABLES)
    assert not unknown, f"these tables are granted but not defined in the metadata: {unknown}"


def test_a_table_is_classified_exactly_once() -> None:
    """Read-write and audit-append are different trust levels; overlap hides the weaker."""
    lists = _grant_lists()
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []
    for name, tables in sorted(lists.items()):
        for table in sorted(tables):
            if table in seen:
                duplicates.append((table, seen[table], name))
            seen[table] = name
    assert not duplicates, f"these tables appear in more than one grant list: {duplicates}"
