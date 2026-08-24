from korpus.application.doctrine_impact import training_impact
from korpus.domain.learning import (
    CourseModule,
    CourseVersion,
    LearningObjective,
    Lesson,
    LessonBlock,
    SourceBinding,
)


def test_source_version_change_identifies_training_review_surface():
    binding = SourceBinding(
        id="b1", document_id="d1", version_id="v-old", evidence_span_ids=frozenset({"s1"})
    )
    lesson = Lesson(
        id="l1",
        ordinal=0,
        title="Lesson one",
        objectives=(LearningObjective(id="o1", statement="Understand approved material"),),
        source_bindings=(binding,),
        blocks=(
            LessonBlock(
                id="blk1",
                ordinal=0,
                kind="text",
                title="Text",
                source_binding_ids=frozenset({"b1"}),
            ),
        ),
    )
    version = CourseVersion(
        id="cv1",
        course_id="c1",
        revision="1",
        modules=(CourseModule(id="m1", ordinal=0, title="Module", lessons=(lesson,)),),
    )
    impact = training_impact(
        version, document_id="d1", previous_version_id="v-old", current_version_id="v-new"
    )
    assert impact.changed_binding_ids == ("b1",)
    assert impact.affected_lesson_ids == ("l1",)
    assert impact.affected_objective_ids == ("o1",)
