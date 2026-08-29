"""Normalized immutable operational competency framework revisions."""

from sqlalchemy import Column, DateTime, ForeignKeyConstraint, String, Table

from korpus.infrastructure.schema import metadata

competency_frameworks = Table(
    "competency_frameworks",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("revision", String(120), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

operational_roles = Table(
    "operational_roles",
    metadata,
    Column("framework_id", String(128), primary_key=True),
    Column("framework_revision", String(120), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("title", String(300), nullable=False),
    ForeignKeyConstraint(
        ["framework_id", "framework_revision"],
        ["competency_frameworks.id", "competency_frameworks.revision"],
        ondelete="CASCADE",
    ),
)

operational_tasks = Table(
    "operational_tasks",
    metadata,
    Column("framework_id", String(128), primary_key=True),
    Column("framework_revision", String(120), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("statement", String(1000), nullable=False),
    Column("conditions", String(2000), nullable=False),
    Column("standard", String(2000), nullable=False),
    ForeignKeyConstraint(
        ["framework_id", "framework_revision"],
        ["competency_frameworks.id", "competency_frameworks.revision"],
        ondelete="CASCADE",
    ),
)

operational_competencies = Table(
    "operational_competencies",
    metadata,
    Column("framework_id", String(128), primary_key=True),
    Column("framework_revision", String(120), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("statement", String(1000), nullable=False),
    ForeignKeyConstraint(
        ["framework_id", "framework_revision"],
        ["competency_frameworks.id", "competency_frameworks.revision"],
        ondelete="CASCADE",
    ),
)

operational_role_tasks = Table(
    "operational_role_tasks",
    metadata,
    Column("framework_id", String(128), primary_key=True),
    Column("framework_revision", String(120), primary_key=True),
    Column("role_id", String(128), primary_key=True),
    Column("task_id", String(128), primary_key=True),
    ForeignKeyConstraint(
        ["framework_id", "framework_revision", "role_id"],
        [
            "operational_roles.framework_id",
            "operational_roles.framework_revision",
            "operational_roles.id",
        ],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["framework_id", "framework_revision", "task_id"],
        [
            "operational_tasks.framework_id",
            "operational_tasks.framework_revision",
            "operational_tasks.id",
        ],
        ondelete="CASCADE",
    ),
)

operational_task_competencies = Table(
    "operational_task_competencies",
    metadata,
    Column("framework_id", String(128), primary_key=True),
    Column("framework_revision", String(120), primary_key=True),
    Column("task_id", String(128), primary_key=True),
    Column("competency_id", String(128), primary_key=True),
    ForeignKeyConstraint(
        ["framework_id", "framework_revision", "task_id"],
        [
            "operational_tasks.framework_id",
            "operational_tasks.framework_revision",
            "operational_tasks.id",
        ],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["framework_id", "framework_revision", "competency_id"],
        [
            "operational_competencies.framework_id",
            "operational_competencies.framework_revision",
            "operational_competencies.id",
        ],
        ondelete="CASCADE",
    ),
)

COMPETENCY_TABLES = (
    competency_frameworks,
    operational_roles,
    operational_tasks,
    operational_competencies,
    operational_role_tasks,
    operational_task_competencies,
)
