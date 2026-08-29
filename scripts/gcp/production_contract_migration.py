"""Migration admission predicates for the production lane."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the group modules are imported *by* production_contract, not before it
    from scripts.gcp.production_contract import Sources


def evaluate(s: Sources) -> list[tuple[str, bool, str]]:
    workflow = s.production_workflow
    return [
        (
            "EXPAND_CONTRACT_MIGRATION_ADMISSION",
            "name: Validate migration expand-contract compatibility" in workflow
            and "python scripts/gcp/validate_migration_compatibility.py" in workflow
            and workflow.index("name: Validate migration expand-contract compatibility")
            < workflow.index("name: Materialize migration job before application services"),
            "migration history is immutable and post-baseline schema changes are admitted as expand-only before the live migration job",
        )
    ]
