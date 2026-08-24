from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class CohortVerdict:
    complete: bool
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    duplicates: tuple[str, ...]


def validate_complete_cohort(expected_ids: Iterable[str], rows: Iterable[Mapping[str, object]]) -> CohortVerdict:
    expected = tuple(str(item) for item in expected_ids)
    if not expected or len(expected) != len(set(expected)):
        raise ValueError("expected cohort IDs must be non-empty and unique")
    observed = [str(row.get("case_id", "")) for row in rows]
    counts = {item: observed.count(item) for item in set(observed)}
    duplicates = tuple(sorted(item for item, count in counts.items() if item and count > 1))
    observed_set = {item for item in observed if item}
    expected_set = set(expected)
    missing = tuple(sorted(expected_set - observed_set))
    unexpected = tuple(sorted(observed_set - expected_set))
    complete = not missing and not unexpected and not duplicates and len(observed) == len(expected)
    return CohortVerdict(complete, missing, unexpected, duplicates)
