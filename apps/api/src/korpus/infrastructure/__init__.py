"""Infrastructure package registration.

Physical-schema fragments that live outside ``schema.py`` are imported eagerly so the
canonical SQLAlchemy ``metadata`` is complete before repository initialization or Alembic
reads it. Behavioural adapters are not imported here.
"""

from korpus.infrastructure import capability_effect_schema as _capability_effect_schema  # noqa: F401
