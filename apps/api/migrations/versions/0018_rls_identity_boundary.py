"""non-forgeable PostgreSQL RLS identity boundary

Revision ID: 0018_rls_identity_boundary
Revises: 0017_approval_provenance_boundary
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_rls_identity_boundary"
down_revision: str | None = "0017_approval_provenance_boundary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS = "public.korpus_rls_"
_WRITER = f"('admin' = ANY({_RLS}roles()) OR 'curator' = ANY({_RLS}roles()))"
_ADMIN = f"('admin' = ANY({_RLS}roles()))"


def _document_visible(alias: str = "documents") -> str:
    elements = f"jsonb_array_elements_text(COALESCE({alias}.compartments_json, '[]')::jsonb)"
    return f"""
        {alias}.access_tier <= {_RLS}clearance()
        AND {alias}.corpus_id = ANY({_RLS}corpora())
        AND {alias}.classification = ANY({_RLS}classifications())
        AND NOT EXISTS (
            SELECT 1 FROM {elements} AS compartment(value)
            WHERE NOT (compartment.value = ANY({_RLS}compartments()))
        )
    """


def _replace_policies(*, trusted: bool) -> None:
    if trusted:
        visible = _document_visible()
        writer = _WRITER
        admin = _ADMIN
    else:
        clearance = "COALESCE(NULLIF(current_setting('korpus.clearance', true), ''), '-1')::int"
        corpora = "string_to_array(COALESCE(current_setting('korpus.corpora', true), ''), ',')"
        classes = "string_to_array(COALESCE(current_setting('korpus.classifications', true), ''), ',')"
        compartments = "string_to_array(COALESCE(current_setting('korpus.compartments', true), ''), ',')"
        roles = "string_to_array(COALESCE(current_setting('korpus.roles', true), ''), ',')"
        elements = "jsonb_array_elements_text(COALESCE(documents.compartments_json, '[]')::jsonb)"
        visible = f"""
            documents.access_tier <= {clearance}
            AND documents.corpus_id = ANY({corpora})
            AND documents.classification = ANY({classes})
            AND NOT EXISTS (
                SELECT 1 FROM {elements} AS compartment(value)
                WHERE NOT (compartment.value = ANY({compartments}))
            )
        """
        writer = f"('admin' = ANY({roles}) OR 'curator' = ANY({roles}))"
        admin = f"('admin' = ANY({roles}))"

    for table, policies in {
        "documents": ("document_delete", "document_update", "document_insert", "document_select"),
        "document_compartments": (
            "document_compartment_delete",
            "document_compartment_update",
            "document_compartment_insert",
            "document_compartment_select",
        ),
        "document_versions": ("version_delete", "version_update", "version_insert", "version_select"),
        "evidence_spans": (
            "evidence_span_delete",
            "evidence_span_update",
            "evidence_span_insert",
            "evidence_span_select",
        ),
        "span_embeddings": ("embedding_delete", "embedding_update", "embedding_insert", "embedding_select"),
    }.items():
        for policy in policies:
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(f"CREATE POLICY document_select ON documents FOR SELECT USING ({visible})")
    op.execute(
        f"CREATE POLICY document_insert ON documents FOR INSERT WITH CHECK ({writer} AND {visible})"
    )
    op.execute(
        f"CREATE POLICY document_update ON documents FOR UPDATE USING ({writer} AND {visible}) "
        f"WITH CHECK ({writer} AND {visible})"
    )
    op.execute(
        f"CREATE POLICY document_delete ON documents FOR DELETE USING ({admin} AND {visible})"
    )

    visible_compartment = (
        "EXISTS (SELECT 1 FROM documents d WHERE d.id = document_compartments.document_id)"
    )
    op.execute(
        "CREATE POLICY document_compartment_select ON document_compartments FOR SELECT USING "
        f"({visible_compartment})"
    )
    op.execute(
        "CREATE POLICY document_compartment_insert ON document_compartments FOR INSERT WITH CHECK "
        f"({writer} AND {visible_compartment})"
    )
    op.execute(
        "CREATE POLICY document_compartment_update ON document_compartments FOR UPDATE USING "
        f"({writer} AND {visible_compartment}) WITH CHECK ({writer} AND {visible_compartment})"
    )
    op.execute(
        "CREATE POLICY document_compartment_delete ON document_compartments FOR DELETE USING "
        f"({admin} AND {visible_compartment})"
    )

    visible_version = "EXISTS (SELECT 1 FROM documents d WHERE d.id = document_versions.document_id)"
    op.execute(f"CREATE POLICY version_select ON document_versions FOR SELECT USING ({visible_version})")
    op.execute(
        f"CREATE POLICY version_insert ON document_versions FOR INSERT WITH CHECK ({writer} AND {visible_version})"
    )
    op.execute(
        f"CREATE POLICY version_update ON document_versions FOR UPDATE USING ({writer} AND {visible_version}) "
        f"WITH CHECK ({writer} AND {visible_version})"
    )
    op.execute(
        f"CREATE POLICY version_delete ON document_versions FOR DELETE USING ({admin} AND {visible_version})"
    )

    visible_span = """
        EXISTS (
            SELECT 1 FROM document_versions v
            JOIN documents d ON d.id = v.document_id
            WHERE v.id = evidence_spans.version_id
        )
    """
    op.execute(f"CREATE POLICY evidence_span_select ON evidence_spans FOR SELECT USING ({visible_span})")
    op.execute(
        f"CREATE POLICY evidence_span_insert ON evidence_spans FOR INSERT WITH CHECK ({writer} AND {visible_span})"
    )
    op.execute(
        f"CREATE POLICY evidence_span_update ON evidence_spans FOR UPDATE USING ({writer} AND {visible_span}) "
        f"WITH CHECK ({writer} AND {visible_span})"
    )
    op.execute(
        f"CREATE POLICY evidence_span_delete ON evidence_spans FOR DELETE USING ({admin} AND {visible_span})"
    )

    visible_embedding = """
        EXISTS (
            SELECT 1 FROM evidence_spans s
            JOIN document_versions v ON v.id = s.version_id
            JOIN documents d ON d.id = v.document_id
            WHERE s.id = span_embeddings.span_id
        )
    """
    op.execute(f"CREATE POLICY embedding_select ON span_embeddings FOR SELECT USING ({visible_embedding})")
    op.execute(
        f"CREATE POLICY embedding_insert ON span_embeddings FOR INSERT WITH CHECK ({writer} AND {visible_embedding})"
    )
    op.execute(
        f"CREATE POLICY embedding_update ON span_embeddings FOR UPDATE USING ({writer} AND {visible_embedding}) "
        f"WITH CHECK ({writer} AND {visible_embedding})"
    )
    op.execute(
        f"CREATE POLICY embedding_delete ON span_embeddings FOR DELETE USING ({admin} AND {visible_embedding})"
    )


def _create_context_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION public.korpus_prepare_rls_context(
          p_clearance integer, p_corpora jsonb, p_classifications jsonb,
          p_compartments jsonb, p_roles jsonb
        ) RETURNS TABLE(backend_pid integer, transaction_id bigint, session_login name) AS $$
        DECLARE target_pid integer := pg_catalog.pg_backend_pid();
        DECLARE target_tx bigint := pg_catalog.txid_current();
        DECLARE target_login name := session_user;
        BEGIN
          IF p_clearance < 0 OR p_clearance > 3 THEN
            RAISE EXCEPTION 'invalid RLS clearance' USING ERRCODE = '22023';
          END IF;
          IF pg_catalog.jsonb_typeof(p_corpora) <> 'array'
             OR pg_catalog.jsonb_typeof(p_classifications) <> 'array'
             OR pg_catalog.jsonb_typeof(p_compartments) <> 'array'
             OR pg_catalog.jsonb_typeof(p_roles) <> 'array' THEN
            RAISE EXCEPTION 'RLS claims must be JSON arrays' USING ERRCODE = '22023';
          END IF;
          INSERT INTO public.korpus_rls_context AS c (
            backend_pid, transaction_id, session_login, clearance,
            corpora, classifications, compartments, roles,
            confirmed_by_login, prepared_at, confirmed_at
          ) VALUES (
            target_pid, target_tx, target_login, p_clearance,
            ARRAY(SELECT DISTINCT item.value FROM pg_catalog.jsonb_array_elements_text(p_corpora) AS item(value) ORDER BY item.value),
            ARRAY(SELECT DISTINCT item.value FROM pg_catalog.jsonb_array_elements_text(p_classifications) AS item(value) ORDER BY item.value),
            ARRAY(SELECT DISTINCT item.value FROM pg_catalog.jsonb_array_elements_text(p_compartments) AS item(value) ORDER BY item.value),
            ARRAY(SELECT DISTINCT item.value FROM pg_catalog.jsonb_array_elements_text(p_roles) AS item(value) ORDER BY item.value),
            NULL, pg_catalog.clock_timestamp(), NULL
          )
          ON CONFLICT (backend_pid) DO UPDATE SET
            transaction_id = EXCLUDED.transaction_id,
            session_login = EXCLUDED.session_login,
            clearance = EXCLUDED.clearance,
            corpora = EXCLUDED.corpora,
            classifications = EXCLUDED.classifications,
            compartments = EXCLUDED.compartments,
            roles = EXCLUDED.roles,
            confirmed_by_login = NULL,
            prepared_at = EXCLUDED.prepared_at,
            confirmed_at = NULL;
          RETURN QUERY SELECT target_pid, target_tx, target_login;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.korpus_prepare_rls_context(integer,jsonb,jsonb,jsonb,jsonb) FROM PUBLIC"
    )
    op.execute(
        """
        CREATE FUNCTION public.korpus_confirm_rls_context(
          p_backend_pid integer, p_transaction_id bigint, p_session_login name
        ) RETURNS void AS $$
        DECLARE caller_login name := session_user;
        DECLARE caller_is_app boolean;
        DECLARE caller_is_review boolean;
        DECLARE target_is_app boolean;
        DECLARE target_is_review boolean;
        BEGIN
          caller_is_app := pg_catalog.to_regrole('korpus_app_runtime') IS NOT NULL
            AND pg_catalog.pg_has_role(caller_login, 'korpus_app_runtime', 'MEMBER');
          caller_is_review := pg_catalog.to_regrole('korpus_review_runtime') IS NOT NULL
            AND pg_catalog.pg_has_role(caller_login, 'korpus_review_runtime', 'MEMBER');
          target_is_app := pg_catalog.to_regrole('korpus_app_runtime') IS NOT NULL
            AND pg_catalog.pg_has_role(p_session_login, 'korpus_app_runtime', 'MEMBER');
          target_is_review := pg_catalog.to_regrole('korpus_review_runtime') IS NOT NULL
            AND pg_catalog.pg_has_role(p_session_login, 'korpus_review_runtime', 'MEMBER');
          IF NOT ((caller_is_app AND target_is_review) OR (caller_is_review AND target_is_app)) THEN
            RAISE EXCEPTION 'RLS context requires confirmation by the opposite database identity'
              USING ERRCODE = '42501';
          END IF;
          UPDATE public.korpus_rls_context
          SET confirmed_by_login = caller_login, confirmed_at = pg_catalog.clock_timestamp()
          WHERE backend_pid = p_backend_pid
            AND transaction_id = p_transaction_id
            AND session_login = p_session_login
            AND confirmed_by_login IS NULL;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'pending RLS context not found' USING ERRCODE = '55000';
          END IF;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.korpus_confirm_rls_context(integer,bigint,name) FROM PUBLIC"
    )
    for name, sql_type, fallback, column in (
        ("clearance", "integer", "-1", "clearance"),
        ("corpora", "text[]", "ARRAY[]::text[]", "corpora"),
        ("classifications", "text[]", "ARRAY[]::text[]", "classifications"),
        ("compartments", "text[]", "ARRAY[]::text[]", "compartments"),
        ("roles", "text[]", "ARRAY[]::text[]", "roles"),
    ):
        op.execute(
            f"""
            CREATE FUNCTION public.korpus_rls_{name}() RETURNS {sql_type} AS $$
              SELECT COALESCE(
                (SELECT c.{column} FROM public.korpus_rls_context AS c
                 WHERE c.backend_pid = pg_catalog.pg_backend_pid()
                   AND c.transaction_id = pg_catalog.txid_current()
                   AND c.session_login = session_user
                   AND c.confirmed_by_login IS NOT NULL),
                {fallback}
              )
            $$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog
            """
        )
        op.execute(f"REVOKE ALL ON FUNCTION public.korpus_rls_{name}() FROM PUBLIC")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE TABLE public.korpus_rls_context (
          backend_pid integer PRIMARY KEY,
          transaction_id bigint NOT NULL,
          session_login name NOT NULL,
          clearance integer NOT NULL CHECK (clearance >= 0 AND clearance <= 3),
          corpora text[] NOT NULL,
          classifications text[] NOT NULL,
          compartments text[] NOT NULL,
          roles text[] NOT NULL,
          confirmed_by_login name,
          prepared_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
          confirmed_at timestamptz
        )
        """
    )
    op.execute("REVOKE ALL ON TABLE public.korpus_rls_context FROM PUBLIC")
    _create_context_functions()
    _replace_policies(trusted=True)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _replace_policies(trusted=False)
    for name in ("roles", "compartments", "classifications", "corpora", "clearance"):
        op.execute(f"DROP FUNCTION IF EXISTS public.korpus_rls_{name}()")
    op.execute("DROP FUNCTION IF EXISTS public.korpus_confirm_rls_context(integer,bigint,name)")
    op.execute(
        "DROP FUNCTION IF EXISTS public.korpus_prepare_rls_context(integer,jsonb,jsonb,jsonb,jsonb)"
    )
    op.execute("DROP TABLE IF EXISTS public.korpus_rls_context")
