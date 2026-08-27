"""Compute deterministic training impact from source-bound doctrine changes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from korpus.domain.learning import CourseVersion


class DoctrineTrainingImpact(BaseModel):
    model_config = ConfigDict(frozen=True)
    changed_binding_ids: tuple[str, ...]
    affected_lesson_ids: tuple[str, ...]
    affected_objective_ids: tuple[str, ...]


def training_impact(
    version: CourseVersion,
    *,
    document_id: str,
    previous_version_id: str,
    current_version_id: str,
) -> DoctrineTrainingImpact:
    """Identify training content that references a replaced source version.

    The function intentionally does not infer semantic equivalence between revisions.
    Any exact source-version replacement is treated as requiring review for all objectives
    in lessons bound to that source, preserving fail-closed training semantics.
    """
    if previous_version_id == current_version_id:
        return DoctrineTrainingImpact(
            changed_binding_ids=(), affected_lesson_ids=(), affected_objective_ids=()
        )
    bindings: set[str] = set()
    lessons: set[str] = set()
    objectives: set[str] = set()
    for module in version.modules:
        for lesson in module.lessons:
            matched = [
                binding
                for binding in lesson.source_bindings
                if binding.document_id == document_id and binding.version_id == previous_version_id
            ]
            if not matched:
                continue
            bindings.update(item.id for item in matched)
            lessons.add(lesson.id)
            objectives.update(item.id for item in lesson.objectives)
    return DoctrineTrainingImpact(
        changed_binding_ids=tuple(sorted(bindings)),
        affected_lesson_ids=tuple(sorted(lessons)),
        affected_objective_ids=tuple(sorted(objectives)),
    )
