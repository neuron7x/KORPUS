"""bind RLS claims to backend incarnation, transaction, and login

Revision ID: 0019_rls_binding_backend_identity
Revises: 0018_nonforgeable_rls_identity
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019_rls_binding_backend_identity"
down_revision: str | None = "0018_nonforgeable_rls_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backend_start_expression() -> str:
    return (
        "(SELECT a.backend_start FROM pg_catalog.pg_stat_activity a "
        "WHERE a.pid = pg_catalog.pg_backend_pid())"
    )


def _binding_predicate() -> str:
    return (
        "b.backend_pid = pg_catalog.pg_backend_pid() "
        f"AND b.backend_start = {_backend_start_expression()} "
        "AND b.transaction_id = pg_catalog.pg_current_xact_id()::text "
        "AND b.login_name = session_user"
    )


def _install_v19_accessors() -> None:
    predicate = _binding_predicate()
    accessors = {
        "korpus_rls_clearance": (
            "integer",
            "COALESCE((SELECT b.clearance FROM public.korpus_rls_identity_bindings b "
            f"WHERE {predicate}), -1)",
        ),
        "korpus_rls_corpora": (
            "text[]",
            "COALESCE((SELECT b.corpora FROM public.korpus_rls_identity_bindings b "
            f"WHERE {predicate}), ARRAY[]::text[])",
        ),
        "korpus_rls_classifications": (
            "text[]",
            "COALESCE((SELECT b.classifications FROM public.korpus_rls_identity_bindings b "
            f"WHERE {predicate}), ARRAY[]::text[])",
        ),
        "korpus_rls_compartments": (
            "text[]",
            "COALESCE((SELECT b.compartments FROM public.korpus_rls_identity_bindings b "
            f"WHERE {predicate}), ARRAY[]::text[])",
        ),
        "korpus_rls_roles": (
            "text[]",
            "COALESCE((SELECT b.roles FROM public.korpus_rls_identity_bindings b "
            f"WHERE {predicate}), ARRAY[]::text[])",
        ),
    }
    for name, (return_type, expression) in accessors.items():
        op.execute(
            f"CREATE OR REPLACE FUNCTION {name}() RETURNS {return_type} AS $$ SELECT {expression} $$ "
            "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog"
        )


def _install_v18_accessors() -> None:
    predicate = (
        "b.backend_pid = pg_catalog.pg_backend_pid() "
        "AND b.transaction_id = pg_catalog.pg_current_xact_id()::text"
    )
    accessors = {
        "korpus_rls_clearance": (
            "integer",
            "COALESCE((SELECT b.clearance FROM public.korpus_rls_identity_bindings b "
            f"WHERE {predicate}), -1)",
        ),
        "korpus_rls_corpora": (
            "text[]",
            "COALESCE((SELECT b.corpora FROM public.korpus_rls_identity_bindings b "
            f"WHERE {predicate}), ARRAY[]::text[])",
        ),
        "korpus_rls_classifications": (
            "text[]",
            "COALESCE((SELECT b.classifications FROM public.korpus_rls_identity_bindings b "
            f"WHERE {predicate}), ARRAY[]::text[])",
        ),
        "korpus_rls_compartments": (
            "text[]",
            "COALESCE((SELECT b.compartments FROM public.korpus_rls_identity_bindings b "
            f"WHERE {predicate}), ARRAY[]::text[])",
        ),
        "korpus_rls_roles": (
            "text[]",
            "COALESCE((SELECT b.roles FROM public.korpus_rls_identity_bindings b "
            f"WHERE {predicate}), ARRAY[]::text[])",
        ),
    }
    for name, (return_type, expression) in accessors.items():
        op.execute(
            f"CREATE OR REPLACE FUNCTION {name}() RETURNS {return_type} AS $$ SELECT {expression} $$ "
            "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog"
        )


def _install_v19_binder() -> None:
    op.execute(
        """
        CREATE FUNCTION korpus_bind_rls_identity(
          p_backend_pid integer, p_backend_start timestamptz, p_transaction_id text,
          p_login_name text, p_subject text, p_clearance integer, p_corpora text,
          p_classifications text, p_compartments text, p_roles text
        ) RETURNS void AS $$
        DECLARE target_ok boolean;
        BEGIN
          IF pg_catalog.to_regrole('korpus_identity_runtime') IS NULL
             OR NOT pg_catalog.pg_has_role(session_user, 'korpus_identity_runtime', 'MEMBER') THEN
            RAISE EXCEPTION 'RLS identity binding requires broker login' USING ERRCODE = '42501';
          END IF;
          IF pg_catalog.to_regrole('korpus_app_runtime') IS NULL
             OR pg_catalog.to_regrole('korpus_review_runtime') IS NULL THEN
            RAISE EXCEPTION 'RLS target roles are unavailable' USING ERRCODE = '42501';
          END IF;
          SELECT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_stat_activity a
            JOIN pg_catalog.pg_roles r ON r.rolname = a.usename
            WHERE a.pid = p_backend_pid
              AND a.backend_start = p_backend_start
              AND a.usename = p_login_name
              AND a.datname = pg_catalog.current_database()
              AND NOT r.rolsuper AND NOT r.rolbypassrls
              AND (
                pg_catalog.pg_has_role(a.usename, 'korpus_app_runtime', 'MEMBER')
                OR pg_catalog.pg_has_role(a.usename, 'korpus_review_runtime', 'MEMBER')
              )
          ) INTO target_ok;
          IF NOT target_ok THEN
            RAISE EXCEPTION 'RLS identity target does not match backend incarnation/login'
              USING ERRCODE = '42501';
          END IF;
          IF p_transaction_id !~ '^[0-9]+$' OR p_login_name = '' OR p_subject = ''
             OR p_clearance < 0 OR p_clearance > 3 THEN
            RAISE EXCEPTION 'invalid RLS identity binding' USING ERRCODE = '22023';
          END IF;
          DELETE FROM public.korpus_rls_identity_bindings
          WHERE backend_pid = p_backend_pid
            AND (
              backend_start <> p_backend_start
              OR transaction_id <> p_transaction_id
              OR login_name <> p_login_name
            );
          DELETE FROM public.korpus_rls_identity_bindings
          WHERE bound_at < pg_catalog.statement_timestamp() - interval '1 day';
          INSERT INTO public.korpus_rls_identity_bindings(
            backend_pid, backend_start, transaction_id, login_name, subject, clearance,
            corpora, classifications, compartments, roles
          ) VALUES (
            p_backend_pid, p_backend_start, p_transaction_id, p_login_name, p_subject, p_clearance,
            CASE WHEN p_corpora = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_corpora, ',') END,
            CASE WHEN p_classifications = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_classifications, ',') END,
            CASE WHEN p_compartments = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_compartments, ',') END,
            CASE WHEN p_roles = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_roles, ',') END
          ) ON CONFLICT (backend_pid, backend_start, transaction_id, login_name) DO NOTHING;
          IF NOT FOUND AND NOT EXISTS (
            SELECT 1 FROM public.korpus_rls_identity_bindings b
            WHERE b.backend_pid = p_backend_pid AND b.backend_start = p_backend_start
              AND b.transaction_id = p_transaction_id AND b.login_name = p_login_name
              AND b.subject = p_subject AND b.clearance = p_clearance
              AND b.corpora = CASE WHEN p_corpora = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_corpora, ',') END
              AND b.classifications = CASE WHEN p_classifications = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_classifications, ',') END
              AND b.compartments = CASE WHEN p_compartments = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_compartments, ',') END
              AND b.roles = CASE WHEN p_roles = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_roles, ',') END
          ) THEN
            RAISE EXCEPTION 'RLS identity is already bound differently for this transaction'
              USING ERRCODE = '42501';
          END IF;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "korpus_bind_rls_identity(integer,timestamptz,text,text,text,integer,text,text,text,text) "
        "FROM PUBLIC"
    )


def _install_v18_binder() -> None:
    op.execute(
        """
        CREATE FUNCTION korpus_bind_rls_identity(
          p_backend_pid integer, p_transaction_id text, p_subject text, p_clearance integer,
          p_corpora text, p_classifications text, p_compartments text, p_roles text
        ) RETURNS void AS $$
        DECLARE target_ok boolean;
        BEGIN
          IF pg_catalog.to_regrole('korpus_identity_runtime') IS NULL
             OR NOT pg_catalog.pg_has_role(session_user, 'korpus_identity_runtime', 'MEMBER') THEN
            RAISE EXCEPTION 'RLS identity binding requires broker login' USING ERRCODE = '42501';
          END IF;
          SELECT EXISTS (
            SELECT 1 FROM pg_catalog.pg_stat_activity a
            JOIN pg_catalog.pg_roles r ON r.rolname = a.usename
            WHERE a.pid = p_backend_pid AND a.datname = pg_catalog.current_database()
              AND NOT r.rolsuper AND NOT r.rolbypassrls
              AND (
                pg_catalog.pg_has_role(a.usename, 'korpus_app_runtime', 'MEMBER')
                OR pg_catalog.pg_has_role(a.usename, 'korpus_review_runtime', 'MEMBER')
              )
          ) INTO target_ok;
          IF NOT target_ok THEN
            RAISE EXCEPTION 'RLS identity target is not an application/review backend'
              USING ERRCODE = '42501';
          END IF;
          IF p_transaction_id !~ '^[0-9]+$' OR p_subject = ''
             OR p_clearance < 0 OR p_clearance > 3 THEN
            RAISE EXCEPTION 'invalid RLS identity binding' USING ERRCODE = '22023';
          END IF;
          DELETE FROM public.korpus_rls_identity_bindings
          WHERE backend_pid = p_backend_pid AND transaction_id <> p_transaction_id;
          INSERT INTO public.korpus_rls_identity_bindings(
            backend_pid, transaction_id, subject, clearance, corpora,
            classifications, compartments, roles
          ) VALUES (
            p_backend_pid, p_transaction_id, p_subject, p_clearance,
            CASE WHEN p_corpora = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_corpora, ',') END,
            CASE WHEN p_classifications = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_classifications, ',') END,
            CASE WHEN p_compartments = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_compartments, ',') END,
            CASE WHEN p_roles = '' THEN ARRAY[]::text[] ELSE pg_catalog.string_to_array(p_roles, ',') END
          ) ON CONFLICT (backend_pid, transaction_id) DO NOTHING;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "korpus_bind_rls_identity(integer,text,text,integer,text,text,text,text) FROM PUBLIC"
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("TRUNCATE TABLE korpus_rls_identity_bindings")
    op.execute("ALTER TABLE korpus_rls_identity_bindings ADD COLUMN backend_start timestamptz NOT NULL")
    op.execute("ALTER TABLE korpus_rls_identity_bindings ADD COLUMN login_name text NOT NULL")
    op.execute("ALTER TABLE korpus_rls_identity_bindings DROP CONSTRAINT korpus_rls_identity_bindings_pkey")
    op.execute(
        "ALTER TABLE korpus_rls_identity_bindings ADD PRIMARY KEY "
        "(backend_pid, backend_start, transaction_id, login_name)"
    )
    op.execute(
        "DROP FUNCTION korpus_bind_rls_identity(integer,text,text,integer,text,text,text,text)"
    )
    _install_v19_binder()
    _install_v19_accessors()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "DROP FUNCTION "
        "korpus_bind_rls_identity(integer,timestamptz,text,text,text,integer,text,text,text,text)"
    )
    _install_v18_binder()
    _install_v18_accessors()
    op.execute("TRUNCATE TABLE korpus_rls_identity_bindings")
    op.execute("ALTER TABLE korpus_rls_identity_bindings DROP CONSTRAINT korpus_rls_identity_bindings_pkey")
    op.execute("ALTER TABLE korpus_rls_identity_bindings DROP COLUMN login_name")
    op.execute("ALTER TABLE korpus_rls_identity_bindings DROP COLUMN backend_start")
    op.execute("ALTER TABLE korpus_rls_identity_bindings ADD PRIMARY KEY (backend_pid, transaction_id)")
