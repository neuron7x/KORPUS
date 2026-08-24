from __future__ import annotations

import pytest
from korpus.domain.learning import (
    CourseModule,
    CourseVersion,
    LearningObjective,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    SourceBinding,
)
from korpus.domain.operational_competency import (
    AlignmentViolation,
    Competency,
    CompetencyFramework,
    OperationalRole,
    OperationalTask,
    validate_course_alignment,
)
from pydantic import ValidationError


def _framework() -> CompetencyFramework:
    return CompetencyFramework(
        id="framework.medical",
        revision="2026-08-24",
        roles=(OperationalRole(id="role.medic", title="Combat medic", task_ids={"task.assess"}),),
        tasks=(
            OperationalTask(
                id="task.assess",
                statement="Assess a casualty",
                conditions="Under the approved training scenario",
                standard="Complete every required assessment step",
                competency_ids={"competency.safety", "competency.sequence"},
            ),
        ),
        competencies=(
            Competency(id="competency.safety", statement="Apply the safety check"),
            Competency(id="competency.sequence", statement="Use the approved sequence"),
        ),
    )


def _course(*competency_ids: str) -> CourseVersion:
    binding = SourceBinding(
        id="binding",
        document_id="document",
        version_id="version",
        evidence_span_ids={"span"},
    )
    return CourseVersion(
        id="course-v1",
        course_id="course",
        revision="1",
        competency_framework_id="framework.medical",
        competency_framework_revision="2026-08-24",
        modules=(
            CourseModule(
                id="module",
                ordinal=0,
                title="Operational module",
                lessons=(
                    Lesson(
                        id="lesson",
                        ordinal=0,
                        title="Assessment lesson",
                        objectives=(
                            LearningObjective(
                                id="objective",
                                statement="Perform the task",
                                competency_ids=frozenset(competency_ids),
                            ),
                        ),
                        source_bindings=(binding,),
                        blocks=(
                            LessonBlock(
                                id="block",
                                ordinal=0,
                                kind=LessonBlockKind.ACTIVITY,
                                title="Evidence-bound practice",
                                source_binding_ids={binding.id},
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def test_complete_conjunctive_mapping_aligns_role() -> None:
    result = validate_course_alignment(
        _course("competency.safety", "competency.sequence"),
        _framework(),
        role_id="role.medic",
    )
    assert result.aligned
    assert result.covered_task_ids == ("task.assess",)


def test_one_missing_competency_keeps_entire_task_uncovered() -> None:
    result = validate_course_alignment(
        _course("competency.safety"), _framework(), role_id="role.medic"
    )
    assert not result.aligned
    assert result.covered_task_ids == ()
    assert result.uncovered_task_ids == ("task.assess",)
    assert result.violations == (
        f"{AlignmentViolation.MISSING_COMPETENCY_OBJECTIVE}:task.assess:competency.sequence",
    )


def test_unknown_role_fails_closed() -> None:
    result = validate_course_alignment(_course(), _framework(), role_id="role.unknown")
    assert not result.aligned
    assert result.violations == (f"{AlignmentViolation.UNKNOWN_ROLE}:role.unknown",)


def test_unknown_objective_label_cannot_create_coverage() -> None:
    result = validate_course_alignment(
        _course("competency.safety", "competency.sequence", "competency.invented"),
        _framework(),
        role_id="role.medic",
    )
    assert not result.aligned
    assert result.violations == (
        f"{AlignmentViolation.UNKNOWN_OBJECTIVE_COMPETENCY}:competency.invented",
    )


def test_framework_refuses_dangling_task_and_competency_edges() -> None:
    with pytest.raises(ValidationError, match="unknown tasks"):
        CompetencyFramework.model_validate(
            _framework().model_dump()
            | {"roles": [{"id": "role.medic", "title": "Medic", "task_ids": ["x"]}]}
        )


def test_competency_bound_course_requires_exact_framework_revision() -> None:
    with pytest.raises(ValidationError, match="require a framework revision"):
        CourseVersion.model_validate(
            _course("competency.safety").model_dump()
            | {"competency_framework_id": None, "competency_framework_revision": None}
        )

    with pytest.raises(ValidationError, match="must be set together"):
        CourseVersion.model_validate(
            _course().model_dump() | {"competency_framework_revision": None}
        )

    with pytest.raises(ValidationError, match="unknown competencies"):
        CompetencyFramework.model_validate(
            _framework().model_dump()
            | {
                "tasks": [
                    {
                        "id": "task.assess",
                        "statement": "Assess",
                        "conditions": "Given scenario",
                        "standard": "All steps",
                        "competency_ids": ["missing"],
                    }
                ]
            }
        )
