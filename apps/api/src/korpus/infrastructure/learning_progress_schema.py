"""Learner progression persistence separated from immutable course content schema."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, Table

from korpus.infrastructure.schema import metadata

learning_mastery = Table(
    "learning_mastery",
    metadata,
    Column("subject", String(200), primary_key=True),
    Column(
        "course_version_id",
        String(128),
        ForeignKey("learning_course_versions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("objective_id", String(128), primary_key=True),
    Column("state", String(32), nullable=False),
    Column("last_check_id", String(128)),
    Column("source_binding_ids", String(8192), nullable=False, default="[]"),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "state IN ('unseen', 'review_required', 'mastered')", name="ck_learning_mastery_state"
    ),
)
