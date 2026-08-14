"""non-forgeable PostgreSQL RLS transaction identity

Revision ID: 0018_nonforgeable_rls_identity
Revises: 0017_approval_provenance_boundary
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_nonforgeable_rls_identity"
down_revision: str | None = "0017_approval_provenance_boundary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLEARANCE = "public.korpus_rls_clearance()"
_CORPORA = "public.korpus_rls_corpora()"
_CLASSIFICATIONS = "public.korpus_rls_classifications()"
_COMPARTMENTS = "public.korpus_rls_compartments()"
_ROLES = "public.korpus_rls_roles()"


def _document_visible(alias: str = "documents") -> str:
    elements = f"jsonb_array_elements_text(COALESCE({alias}.compartments_json, '[]')::jsonb)"
    return f"""
        {alias}.access_tier <= {_CLEARANCE}
        AND {alias}.corpus_id = ANY({_CORPORA})
        AND {alias}.classification = ANY({_CLASSIFICATIONS})
        AND NOT EXISTS (
            SELECT 1 FROM {elements} AS compartment(value)
            WHERE NOT (compartment.value = ANY({_COMPARTMENTS}))
        )
    """


def _writer() -> str:
    return f"('admin' = ANY({_ROLES}) OR 'curator' = ANY({_ROLES}))"


def _drop_current_policies() -> None:
    policies = {
        "document_compartments": (
            "document_compartment_delete", "document_compartment_update",
            "document_compartment_insert", "document_compartment_select",
        ),
        "span_embeddings": (
            "embedding_delete", "embedding_update", "embedding_insert", "embedding_select",
        ),
        "evidence_spans": (
            "evidence_span_delete", "evidence_span_update",
            "evidence_span_insert", "evidence_span_select",
        ),
        "document_versions": (
            "version_delete", "version_update", "version_insert", "version_select",
        ),
        "documents": ("document_delete", "document_update", "document_insert", "document_select"),
    }
    for table, names in policies.items():
        for name in names:
            op.execute(f"DROP POLICY IF EXISTS {name} ON {table}")


def _install_bound_policies() -> None:
    op.execute(f"CREATE POLICY document_select ON documents FOR SELECT USING ({_document_visible()})")
    op.execute(
        "CREATE POLICY document_insert ON documents FOR INSERT WITH CHECK "
        f"({_writer()} AND {_document_visible()})"
    )
    op.execute(
        "CREATE POLICY document_update ON documents FOR UPDATE USING "
        f"({_writer()} AND {_document_visible()}) WITH CHECK ({_writer()} AND {_document_visible()})"
    )
    op.execute(
        "CREATE POLICY document_delete ON documents FOR DELETE USING "
        f"('admin' = ANY({_ROLES}) AND {_document_visible()})"
    )
    visible_version = "EXISTS (SELECT 1 FROM documents d WHERE d.id = document_versions.document_id)"
    op.execute(f"CREATE POLICY version_select ON document_versions FOR SELECT USING ({visible_version})")
    op.execute(
        "CREATE POLICY version_insert ON document_versions FOR INSERT WITH CHECK "
        f"({_writer()} AND {visible_version})"
    )
    op.execute(
        "CREATE POLICY version_update ON document_versions FOR UPDATE USING "
        f"({_writer()} AND {visible_version}) WITH CHECK ({_writer()} AND {visible_version})"
    )
    op.execute(
        f"CREATE POLICY version_delete ON document_versions FOR DELETE USING "
        f"('admin' = ANY({_ROLES}) AND {visible_version})"
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
        "CREATE POLICY evidence_span_insert ON evidence_spans FOR INSERT WITH CHECK "
        f"({_writer()} AND {visible_span})"
    )
    op.execute(
        "CREATE POLICY evidence_span_update ON evidence_spans FOR UPDATE USING "
        f"({_writer()} AND {visible_span}) WITH CHECK ({_writer()} AND {visible_span})"
    )
    op.execute(
        "CREATE POLICY evidence_span_delete ON evidence_spans FOR DELETE USING "
        f"('admin' = ANY({_ROLES}) AND {visible_span})"
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
        "CREATE POLICY embedding_insert ON span_embeddings FOR INSERT WITH CHECK "
        f"({_writer()} AND {visible_embedding})"
    )
    op.execute(
        "CREATE POLICY embedding_update ON span_embeddings FOR UPDATE USING "
        f"({_writer()} AND {visible_embedding}) WITH CHECK ({_writer()} AND {visible_embedding})"
    )
    op.execute(
        "CREATE POLICY embedding_delete ON span_embeddings FOR DELETE USING "
        f"('admin' = ANY({_ROLES}) AND {visible_embedding})"
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
        f"({_writer()} AND {visible_compartment})"
    )
    op.execute(
        "CREATE POLICY document_compartment_update ON document_compartments FOR UPDATE USING "
        f"({_writer()} AND {visible_compartment}) WITH CHECK ({_writer()} AND {visible_compartment})"
    )
    op.execute(
        "CREATE POLICY document_compartment_delete ON document_compartments FOR DELETE USING "
        f"('admin' = ANY({_ROLES}) AND {visible_compartment})"
    )


def _create_identity_boundary() -> None:
    op.execute(
        """
        CREATE TABLE korpus_rls_identity_bindings (
          backend_pid integer NOT NULL,
          transaction_id text NOT NULL,
          subject text NOT NULL,
          clearance integer NOT NULL CHECK (clearance >= 0 AND clearance <= 3),
          corpora text[] NOT NULL,
          classifications text[] NOT NULL,
          compartments text[] NOT NULL,
          roles text[] NOT NULL,
          bound_at timestamptz NOT NULL DEFAULT statement_timestamp(),
          PRIMARY KEY (backend_pid, transaction_id)
        )
        """
    )
    op.execute("REVOKE ALL ON TABLE korpus_rls_identity_bindings FROM PUBLIC")
    op.execute(
        """
        CREATE FUNCTION korpus_bind_rls_identity(
          p_backend_pid integer, p_transaction_id text, p_subject text, p_clearance integer,
          p_corpora text, p_classifications text, p_compartments text, p_roles text
        ) RETURNS void AS $$
        DECLARE target_ok boolean;
        BEGIN
          IF pg_catalog.to_regrole('korpus_identity_runtime') IS NULL THEN
            RAISE EXCEPTION 'RLS identity broker role is unavailable' USING ERRCODE = '42501';
          END IF;
          IF NOT pg_catalog.pg_has_role(session_user, 'korpus_identity_runtime', 'MEMBER') THEN
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
              AND a.datname = pg_catalog.current_database()
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
          DELETE FROM public.korpus_rls_identity_bindings
          WHERE bound_at < pg_catalog.statement_timestamp() - interval '1 day';
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
          IF NOT FOUND AND NOT EXISTS (
            SELECT 1 FROM public.korpus_rls_identity_bindings b
            WHERE b.backend_pid = p_backend_pid AND b.transaction_id = p_transaction_id
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
    accessors = {
        "korpus_rls_clearance": (
            "integer", "COALESCE((SELECT b.clearance FROM public.korpus_rls_identity_bindings b "
            "WHERE b.backend_pid = pg_catalog.pg_backend_pid() AND "
            "b.transaction_id = pg_catalog.pg_current_xact_id()::text), -1)"
        ),
        "korpus_rls_corpora": (
            "text[]", "COALESCE((SELECT b.corpora FROM public.korpus_rls_identity_bindings b "
            "WHERE b.backend_pid = pg_catalog.pg_backend_pid() AND "
            "b.transaction_id = pg_catalog.pg_current_xact_id()::text), ARRAY[]::text[])"
        ),
        "korpus_rls_classifications": (
            "text[]", "COALESCE((SELECT b.classifications FROM public.korpus_rls_identity_bindings b "
            "WHERE b.backend_pid = pg_catalog.pg_backend_pid() AND "
            "b.transaction_id = pg_catalog.pg_current_xact_id()::text), ARRAY[]::text[])"
        ),
        "korpus_rls_compartments": (
            "text[]", "COALESCE((SELECT b.compartments FROM public.korpus_rls_identity_bindings b "
            "WHERE b.backend_pid = pg_catalog.pg_backend_pid() AND "
            "b.transaction_id = pg_catalog.pg_current_xact_id()::text), ARRAY[]::text[])"
        ),
        "korpus_rls_roles": (
            "text[]", "COALESCE((SELECT b.roles FROM public.korpus_rls_identity_bindings b "
            "WHERE b.backend_pid = pg_catalog.pg_backend_pid() AND "
            "b.transaction_id = pg_catalog.pg_current_xact_id()::text), ARRAY[]::text[])"
        ),
    }
    for name, (return_type, expression) in accessors.items():
        op.execute(
            f"CREATE FUNCTION {name}() RETURNS {return_type} AS $$ SELECT {expression} $$ "
            "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog"
        )
        op.execute(f"REVOKE ALL ON FUNCTION {name}() FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON FUNCTION korpus_bind_rls_identity(integer,text,text,integer,text,text,text,text) FROM PUBLIC"
    )


def _legacy_fragments() -> tuple[str, str, str, str, str]:
    clearance = "COALESCE(NULLIF(current_setting('korpus.clearance', true), ''), '-1')::int"
    corpora = "string_to_array(COALESCE(current_setting('korpus.corpora', true), ''), ',')"
    classifications = "string_to_array(COALESCE(current_setting('korpus.classifications', true), ''), ',')"
    compartments = "string_to_array(COALESCE(current_setting('korpus.compartments', true), ''), ',')"
    roles = "string_to_array(COALESCE(current_setting('korpus.roles', true), ''), ',')"
    return clearance, corpora, classifications, compartments, roles


def _install_legacy_policies() -> None:
    clearance, corpora, classifications, compartments, roles = _legacy_fragments()
    def visible(alias: str = "documents") -> str:
        elements = f"jsonb_array_elements_text(COALESCE({alias}.compartments_json, '[]')::jsonb)"
        return f"""{alias}.access_tier <= {clearance}
        AND {alias}.corpus_id = ANY({corpora})
        AND {alias}.classification = ANY({classifications})
        AND NOT EXISTS (SELECT 1 FROM {elements} AS compartment(value)
        WHERE NOT (compartment.value = ANY({compartments})))"""
    writer = f"('admin' = ANY({roles}) OR 'curator' = ANY({roles}))"
    op.execute(f"CREATE POLICY document_select ON documents FOR SELECT USING ({visible()})")
    op.execute(f"CREATE POLICY document_insert ON documents FOR INSERT WITH CHECK ({writer} AND {visible()})")
    op.execute(f"CREATE POLICY document_update ON documents FOR UPDATE USING ({writer} AND {visible()}) WITH CHECK ({writer} AND {visible()})")
    op.execute(f"CREATE POLICY document_delete ON documents FOR DELETE USING ('admin' = ANY({roles}) AND {visible()})")
    targets = {
        "document_versions": ("version", "EXISTS (SELECT 1 FROM documents d WHERE d.id = document_versions.document_id)"),
        "evidence_spans": ("evidence_span", "EXISTS (SELECT 1 FROM document_versions v JOIN documents d ON d.id = v.document_id WHERE v.id = evidence_spans.version_id)"),
        "span_embeddings": ("embedding", "EXISTS (SELECT 1 FROM evidence_spans s JOIN document_versions v ON v.id = s.version_id JOIN documents d ON d.id = v.document_id WHERE s.id = span_embeddings.span_id)"),
        "document_compartments": ("document_compartment", "EXISTS (SELECT 1 FROM documents d WHERE d.id = document_compartments.document_id)"),
    }
    for table, (prefix, row_visible) in targets.items():
        op.execute(f"CREATE POLICY {prefix}_select ON {table} FOR SELECT USING ({row_visible})")
        op.execute(f"CREATE POLICY {prefix}_insert ON {table} FOR INSERT WITH CHECK ({writer} AND {row_visible})")
        op.execute(f"CREATE POLICY {prefix}_update ON {table} FOR UPDATE USING ({writer} AND {row_visible}) WITH CHECK ({writer} AND {row_visible})")
        op.execute(f"CREATE POLICY {prefix}_delete ON {table} FOR DELETE USING ('admin' = ANY({roles}) AND {row_visible})")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _create_identity_boundary()
    _drop_current_policies()
    _install_bound_policies()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _drop_current_policies()
    _install_legacy_policies()
    for name in (
        "korpus_rls_roles", "korpus_rls_compartments", "korpus_rls_classifications",
        "korpus_rls_corpora", "korpus_rls_clearance",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    op.execute(
        "DROP FUNCTION IF EXISTS korpus_bind_rls_identity(integer,text,text,integer,text,text,text,text)"
    )
    op.execute("DROP TABLE IF EXISTS korpus_rls_identity_bindings")
