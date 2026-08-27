from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .pec_cohort import validate_complete_cohort
from .pec_revision_binding import RevisionBinding


@dataclass(frozen=True)
class JudgmentVerdict:
    admissible: bool
    failures: tuple[str, ...]
    judgments: int


def evaluate_human_judgments(
    rows: Iterable[Mapping[str, object]],
    *,
    expected_case_ids: Iterable[str],
    binding: RevisionBinding,
) -> JudgmentVerdict:
    materialized = list(rows)
    failures: list[str] = []
    cohort = validate_complete_cohort(expected_case_ids, materialized)
    if not cohort.complete:
        failures.append("cohort_incomplete")
    for row in materialized:
        case_id = str(row.get("case_id", ""))
        if str(row.get("actor_type", "")).upper() != "HUMAN":
            failures.append(f"non_human_judgment:{case_id}")
        model_self_judgment = row.get("model_self_judgment")
        if not isinstance(model_self_judgment, bool):
            failures.append(f"invalid_model_self_judgment:{case_id}")
        elif model_self_judgment:
            failures.append(f"model_self_judgment:{case_id}")
        if str(row.get("revision", "")) != binding.revision:
            failures.append(f"revision_mismatch:{case_id}")
        if (
            str(row.get("profile", "")) != binding.profile
            or str(row.get("phase", "")) != binding.phase
        ):
            failures.append(f"profile_phase_mismatch:{case_id}")
        provenance = str(row.get("judgment_provenance_sha256", ""))
        if len(provenance) != 64 or any(ch not in "0123456789abcdef" for ch in provenance):
            failures.append(f"invalid_provenance:{case_id}")
    return JudgmentVerdict(
        not failures and bool(materialized), tuple(sorted(set(failures))), len(materialized)
    )
