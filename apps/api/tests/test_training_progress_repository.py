from datetime import UTC, datetime
from pathlib import Path

from korpus.application.training_progression import LearnerProgress, ObjectiveMastery, ObjectiveState
from uuid import UUID
from sqlalchemy import insert
from korpus.domain.learning import Course, CourseModule, CourseVersion, LearningObjective, Lesson, LessonBlock, SourceBinding
from korpus.domain.models import AccessTier, AuthorityClass, Classification, DocumentRecord, DocumentVersionRecord, EvidenceSpanRecord, ReviewState
from korpus.infrastructure import row_mapping
from korpus.infrastructure.schema import documents, versions, spans
from korpus.infrastructure.learning_repository import SqlLearningRepository
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.training_progress_repository import SqlTrainingProgressRepository



DOC_ID = UUID("11111111-1111-1111-1111-111111111111")
VERSION_ID = UUID("22222222-2222-2222-2222-222222222222")
SPAN_ID = UUID("33333333-3333-3333-3333-333333333333")

def _source(repository):
    doc = DocumentRecord(id=DOC_ID, canonical_title="Canonical source", corpus_id="public", issuer="Authority", jurisdiction="UA", document_type="standard", access_tier=AccessTier.PUBLIC, classification=Classification.PUBLIC)
    version = DocumentVersionRecord(id=VERSION_ID, document_id=DOC_ID, revision="1", source_hash="a"*64, object_key="objects/source", mime_type="text/plain", publication_date=datetime(2026,1,1,tzinfo=UTC).date(), effective_from=datetime(2026,1,1,tzinfo=UTC).date(), effective_until=datetime(2027,1,1,tzinfo=UTC).date(), authority=AuthorityClass.OFFICIAL_UA, review_state=ReviewState.APPROVED, approved_at=datetime(2026,1,2,tzinfo=UTC), approved_by="reviewer", is_current=True)
    span = EvidenceSpanRecord(id=SPAN_ID, version_id=VERSION_ID, ordinal=0, text="Exact authoritative evidence.")
    with repository.engine.begin() as c:
        c.execute(insert(documents).values(**row_mapping.document_values(doc)))
        c.execute(insert(versions).values(**row_mapping.version_values(version)))
        c.execute(insert(spans).values(**row_mapping.span_values(span)))

def _version():
    binding = SourceBinding(id="binding", document_id=str(DOC_ID), version_id=str(VERSION_ID), evidence_span_ids=frozenset({str(SPAN_ID)}))
    lesson = Lesson(id="lesson", ordinal=0, title="Evidence lesson", objectives=(LearningObjective(id="objective", statement="Know the evidence"),), source_bindings=(binding,), blocks=(LessonBlock(id="block", ordinal=0, kind="text", title="Exact evidence block", source_binding_ids=frozenset({binding.id})),))
    return CourseVersion(id="course-v1", course_id="course", revision="1", modules=(CourseModule(id="module", ordinal=0, title="Module", lessons=(lesson,)),))

def test_progress_round_trip_and_atomic_replace(tmp_path: Path):
    base = SqlRepository(f"sqlite:///{tmp_path / 'progress.db'}", "audit-key", audit_anchor_path=tmp_path / "anchor.json")
    base.initialize(); _source(base)
    learning = SqlLearningRepository(base.engine)
    learning.create_course(Course(id="course", specialty_id="public", title="Course"))
    version = _version(); learning.create_version(version)
    repo = SqlTrainingProgressRepository(base.engine)
    first = LearnerProgress(subject="soldier-1", course_version_id=version.id, mastery=(ObjectiveMastery(objective_id="objective", state=ObjectiveState.MASTERED, last_check_id="q1", source_binding_ids=("binding",), updated_at=datetime(2026,8,20,tzinfo=UTC)),))
    repo.save(first)
    assert repo.load("soldier-1", version.id) == first
    changed = first.model_copy(update={"mastery": (first.mastery[0].model_copy(update={"state": ObjectiveState.REVIEW_REQUIRED}),)})
    repo.save(changed)
    assert repo.load("soldier-1", version.id).mastery[0].state is ObjectiveState.REVIEW_REQUIRED
