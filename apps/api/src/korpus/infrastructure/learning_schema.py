"""Normalized immutable learning graph bound to canonical corpus evidence."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Table,
    UniqueConstraint,
)

from korpus.infrastructure.schema import metadata

learning_courses = Table(
    "learning_courses",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("specialty_id", String(64), nullable=False, index=True),
    Column("title", String(500), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

learning_course_versions = Table(
    "learning_course_versions",
    metadata,
    Column("id", String(128), primary_key=True),
    Column(
        "course_id",
        String(128),
        ForeignKey("learning_courses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("revision", String(120), nullable=False),
    Column("competency_framework_id", String(128)),
    Column("competency_framework_revision", String(120)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("course_id", "revision", name="uq_learning_course_revision"),
)

learning_modules = Table(
    "learning_modules",
    metadata,
    Column(
        "course_version_id",
        String(128),
        ForeignKey("learning_course_versions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(128), primary_key=True),
    Column("ordinal", Integer, nullable=False),
    Column("title", String(500), nullable=False),
    UniqueConstraint("course_version_id", "ordinal", name="uq_learning_module_ordinal"),
)

learning_lessons = Table(
    "learning_lessons",
    metadata,
    Column("course_version_id", String(128), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("module_id", String(128), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("title", String(500), nullable=False),
    ForeignKeyConstraint(
        ["course_version_id", "module_id"],
        ["learning_modules.course_version_id", "learning_modules.id"],
        ondelete="CASCADE",
        name="fk_learning_lesson_module",
    ),
    UniqueConstraint(
        "course_version_id", "module_id", "ordinal", name="uq_learning_lesson_ordinal"
    ),
)

learning_objectives = Table(
    "learning_objectives",
    metadata,
    Column("course_version_id", String(128), primary_key=True),
    Column("lesson_id", String(128), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("statement", String(1000), nullable=False),
    ForeignKeyConstraint(
        ["course_version_id", "lesson_id"],
        ["learning_lessons.course_version_id", "learning_lessons.id"],
        ondelete="CASCADE",
        name="fk_learning_objective_lesson",
    ),
)

learning_objective_competencies = Table(
    "learning_objective_competencies",
    metadata,
    Column("course_version_id", String(128), primary_key=True),
    Column("lesson_id", String(128), primary_key=True),
    Column("objective_id", String(128), primary_key=True),
    Column("competency_id", String(128), primary_key=True),
    ForeignKeyConstraint(
        ["course_version_id", "lesson_id", "objective_id"],
        ["learning_objectives.course_version_id", "learning_objectives.lesson_id", "learning_objectives.id"],
        ondelete="CASCADE",
    ),
)

learning_source_bindings = Table(
    "learning_source_bindings",
    metadata,
    Column("course_version_id", String(128), primary_key=True),
    Column("lesson_id", String(128), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column(
        "document_id", String(36), ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    ),
    Column(
        "version_id",
        String(36),
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    ForeignKeyConstraint(
        ["course_version_id", "lesson_id"],
        ["learning_lessons.course_version_id", "learning_lessons.id"],
        ondelete="CASCADE",
        name="fk_learning_binding_lesson",
    ),
)

learning_source_binding_spans = Table(
    "learning_source_binding_spans",
    metadata,
    Column("course_version_id", String(128), primary_key=True),
    Column("lesson_id", String(128), primary_key=True),
    Column("binding_id", String(128), primary_key=True),
    Column(
        "span_id",
        String(36),
        ForeignKey("evidence_spans.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    ForeignKeyConstraint(
        ["course_version_id", "lesson_id", "binding_id"],
        [
            "learning_source_bindings.course_version_id",
            "learning_source_bindings.lesson_id",
            "learning_source_bindings.id",
        ],
        ondelete="CASCADE",
        name="fk_learning_binding_span_binding",
    ),
)

learning_lesson_blocks = Table(
    "learning_lesson_blocks",
    metadata,
    Column("course_version_id", String(128), primary_key=True),
    Column("lesson_id", String(128), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("ordinal", Integer, nullable=False),
    Column("kind", String(32), nullable=False),
    Column("title", String(500), nullable=False),
    ForeignKeyConstraint(
        ["course_version_id", "lesson_id"],
        ["learning_lessons.course_version_id", "learning_lessons.id"],
        ondelete="CASCADE",
        name="fk_learning_block_lesson",
    ),
    UniqueConstraint("course_version_id", "lesson_id", "ordinal", name="uq_learning_block_ordinal"),
    CheckConstraint(
        "kind IN ('text', 'video', 'image', 'scheme', 'activity')", name="ck_learning_block_kind"
    ),
)

learning_block_sources = Table(
    "learning_block_sources",
    metadata,
    Column("course_version_id", String(128), primary_key=True),
    Column("lesson_id", String(128), primary_key=True),
    Column("block_id", String(128), primary_key=True),
    Column("binding_id", String(128), primary_key=True),
    ForeignKeyConstraint(
        ["course_version_id", "lesson_id", "block_id"],
        [
            "learning_lesson_blocks.course_version_id",
            "learning_lesson_blocks.lesson_id",
            "learning_lesson_blocks.id",
        ],
        ondelete="CASCADE",
        name="fk_learning_block_source_block",
    ),
    ForeignKeyConstraint(
        ["course_version_id", "lesson_id", "binding_id"],
        [
            "learning_source_bindings.course_version_id",
            "learning_source_bindings.lesson_id",
            "learning_source_bindings.id",
        ],
        ondelete="CASCADE",
        name="fk_learning_block_source_binding",
    ),
)

learning_prerequisites = Table(
    "learning_prerequisites",
    metadata,
    Column("course_version_id", String(128), primary_key=True),
    Column("lesson_id", String(128), primary_key=True),
    Column("prerequisite_lesson_id", String(128), primary_key=True),
    ForeignKeyConstraint(
        ["course_version_id", "lesson_id"],
        ["learning_lessons.course_version_id", "learning_lessons.id"],
        ondelete="CASCADE",
        name="fk_learning_prerequisite_lesson",
    ),
    ForeignKeyConstraint(
        ["course_version_id", "prerequisite_lesson_id"],
        ["learning_lessons.course_version_id", "learning_lessons.id"],
        ondelete="RESTRICT",
        name="fk_learning_prerequisite_dependency",
    ),
    CheckConstraint(
        "lesson_id <> prerequisite_lesson_id", name="ck_learning_prerequisite_not_self"
    ),
)

learning_publications = Table(
    "learning_publications",
    metadata,
    Column(
        "course_version_id",
        String(128),
        ForeignKey("learning_course_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("state", String(32), nullable=False),
    Column("reviewed_at", DateTime(timezone=True)),
    Column("reviewed_by", String(200)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "state IN ('draft', 'published', 'invalidated', 'retired')",
        name="ck_learning_publication_state",
    ),
    CheckConstraint(
        "state <> 'published' OR (reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)",
        name="ck_learning_publication_review",
    ),
)


LEARNING_TABLES = (
    learning_courses,
    learning_course_versions,
    learning_modules,
    learning_lessons,
    learning_objectives,
    learning_source_bindings,
    learning_source_binding_spans,
    learning_lesson_blocks,
    learning_block_sources,
    learning_prerequisites,
    learning_publications,
)

LEARNING_CONTENT_TABLES = (
    learning_course_versions,
    learning_modules,
    learning_lessons,
    learning_objectives,
    learning_source_bindings,
    learning_source_binding_spans,
    learning_lesson_blocks,
    learning_block_sources,
    learning_prerequisites,
)

# Compatibility re-export after table construction avoids the schema import cycle.
# Register the independent framework graph on the shared metadata.
from korpus.infrastructure.competency_schema import COMPETENCY_TABLES as COMPETENCY_TABLES
from korpus.infrastructure.learning_progress_schema import (
    learning_mastery as learning_mastery,
)
