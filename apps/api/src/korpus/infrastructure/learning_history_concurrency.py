"""Serialize graph edits with publication on their shared lifecycle rows."""

from __future__ import annotations

from sqlalchemy.engine import Connection

_CONTENT_GUARD = """
CREATE OR REPLACE FUNCTION public.korpus_guard_learning_content_immutable()
RETURNS trigger AS $$
DECLARE old_version_id text;
DECLARE new_version_id text;
DECLARE old_course_id text;
DECLARE new_course_id text;
DECLARE lifecycle_state text;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    IF TG_TABLE_NAME = 'learning_course_versions' THEN old_version_id := OLD.id;
    ELSE old_version_id := OLD.course_version_id;
    END IF;
  END IF;
  IF TG_OP <> 'DELETE' THEN
    IF TG_TABLE_NAME = 'learning_course_versions' THEN new_version_id := NEW.id;
    ELSE new_version_id := NEW.course_version_id;
    END IF;
  END IF;
  -- DELETE adds no course association; draft cleanup already removed its lifecycle.
  IF TG_TABLE_NAME = 'learning_course_versions' AND TG_OP <> 'DELETE' THEN
    IF TG_OP = 'UPDATE' THEN old_course_id := OLD.course_id; END IF;
    new_course_id := NEW.course_id;
    -- Creation/reparenting can precede every lifecycle visible to a course edit.
    -- Own both course parents before lifecycle rows; FK KEY SHARE is too weak.
    PERFORM 1 FROM public.learning_courses c
    WHERE c.id IN (old_course_id, new_course_id)
    ORDER BY c.id
    FOR SHARE OF c;
  END IF;
  -- Lock drafts too. A state-filtered query would miss an uncommitted publication.
  -- Initial course-version INSERT precedes its lifecycle in the same transaction;
  -- no row exists to lock then. The writer creates draft before inserting children.
  FOR lifecycle_state IN
    SELECT p.state FROM public.learning_publications p
    WHERE p.course_version_id IN (old_version_id, new_version_id)
    ORDER BY p.course_version_id
    FOR SHARE OF p
  LOOP
    IF lifecycle_state IN ('published', 'invalidated', 'retired') THEN
      RAISE EXCEPTION 'published learning history is immutable' USING ERRCODE = '42501';
    END IF;
  END LOOP;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
"""

_COURSE_GUARD = """
CREATE OR REPLACE FUNCTION public.korpus_guard_learning_course_identity()
RETURNS trigger AS $$
DECLARE old_course_id text;
DECLARE new_course_id text;
DECLARE lifecycle_state text;
BEGIN
  old_course_id := OLD.id;
  IF TG_OP <> 'DELETE' THEN new_course_id := NEW.id; END IF;
  FOR lifecycle_state IN
    SELECT p.state FROM public.learning_course_versions cv
    JOIN public.learning_publications p ON p.course_version_id = cv.id
    WHERE cv.course_id IN (old_course_id, new_course_id)
    ORDER BY p.course_version_id
    FOR SHARE OF p
  LOOP
    IF lifecycle_state IN ('published', 'invalidated', 'retired') THEN
      RAISE EXCEPTION 'course identity used by published history is immutable'
        USING ERRCODE = '42501';
    END IF;
  END LOOP;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
"""


def install_postgres_learning_history_locks(connection: Connection) -> None:
    """Replace guard bodies in the forward migration, preserving their existing ACLs."""
    connection.exec_driver_sql(_CONTENT_GUARD)
    connection.exec_driver_sql(_COURSE_GUARD)
