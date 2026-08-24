"""Migration admission predicates for the production lane."""
from __future__ import annotations


def evaluate(s: object) -> list[tuple[str, bool, str]]:
    workflow = s.production_workflow
    return [(
        "EXPAND_CONTRACT_MIGRATION_ADMISSION",
        'name: Validate migration expand-contract compatibility' in workflow
        and 'python scripts/gcp/validate_migration_compatibility.py' in workflow
        and workflow.index('name: Validate migration expand-contract compatibility')
            < workflow.index('name: Materialize migration job before application services'),
        "migration history is immutable and post-baseline schema changes are admitted as expand-only before the live migration job",
    )]
