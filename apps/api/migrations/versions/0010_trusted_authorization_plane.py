"""transaction-bound database authorization capabilities

Revision ID: 0010_trusted_authorization_plane
Revises: 0009_reviewer_credentials
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0010_trusted_authorization_plane"
down_revision: Union[str, None] = "0009_reviewer_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _legacy_roles() -> str:
    return "string_to_array(COALESCE(current_setting('korpus.roles', true), ''), ',')"


def _legacy_visible(alias: str = "documents") -> str:
    return f"""
        {alias}.access_tier <= COALESCE(NULLIF(current_setting('korpus.clearance', true), ''), '-1')::int
        AND {alias}.corpus_id = ANY(string_to_array(COALESCE(current_setting('korpus.corpora', true), ''), ','))
        AND {alias}.classification = ANY(string_to_array(COALESCE(current_setting('korpus.classifications', true), ''), ','))
        AND NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(COALESCE({alias}.compartments_json, '[]')::jsonb) compartment(value)
            WHERE NOT (compartment.value = ANY(string_to_array(COALESCE(current_setting('korpus.compartments', true), ''), ',')))
        )
    """


def _drop_current_policies() -> None:
    for table, policies in {
        "span_embeddings": ("embedding_delete", "embedding_update", "embedding_insert", "embedding_select"),
        "evidence_spans": ("evidence_span_delete", "evidence_span_update", "evidence_span_insert", "evidence_span_select"),
        "document_versions": ("version_delete", "version_update", "version_insert", "version_select"),
        "document_compartments": (
            "document_compartment_delete", "document_compartment_update",
            "document_compartment_insert", "document_compartment_select",
        ),
        "documents": ("document_delete", "document_update", "document_insert", "document_select"),
    }.items():
        for policy in policies:
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")


def _create_capability_policies() -> None:
    claims = "korpus_auth.claims()"
    readable = "korpus_auth.has_operation('read')"
    visible = f"""
        {readable}
        AND documents.access_tier <= COALESCE(({claims}->>'clearance')::int, -1)
        AND documents.corpus_id = ANY(korpus_auth.claim_array('corpora'))
        AND documents.classification = ANY(korpus_auth.claim_array('classifications'))
        AND NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(COALESCE(documents.compartments_json, '[]')::jsonb) compartment(value)
            WHERE NOT (compartment.value = ANY(korpus_auth.claim_array('compartments')))
        )
    """
    writer = "korpus_auth.has_operation('write') AND (korpus_auth.has_role('admin') OR korpus_auth.has_role('curator'))"
    deleter = "korpus_auth.has_operation('delete') AND korpus_auth.has_role('admin')"
    op.execute(f"CREATE POLICY document_select ON documents FOR SELECT USING ({visible})")
    op.execute(f"CREATE POLICY document_insert ON documents FOR INSERT WITH CHECK ({writer} AND {visible})")
    op.execute(f"CREATE POLICY document_update ON documents FOR UPDATE USING ({writer} AND {visible}) WITH CHECK ({writer} AND {visible})")
    op.execute(f"CREATE POLICY document_delete ON documents FOR DELETE USING ({deleter} AND {visible})")

    descendants = {
        "document_versions": ("version", "EXISTS (SELECT 1 FROM documents d WHERE d.id = document_versions.document_id)"),
        "evidence_spans": ("evidence_span", "EXISTS (SELECT 1 FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE v.id=evidence_spans.version_id)"),
        "span_embeddings": ("embedding", "EXISTS (SELECT 1 FROM evidence_spans s JOIN document_versions v ON v.id=s.version_id JOIN documents d ON d.id=v.document_id WHERE s.id=span_embeddings.span_id)"),
        "document_compartments": ("document_compartment", "EXISTS (SELECT 1 FROM documents d WHERE d.id=document_compartments.document_id)"),
    }
    for table, (prefix, row_visible) in descendants.items():
        op.execute(f"CREATE POLICY {prefix}_select ON {table} FOR SELECT USING ({readable} AND {row_visible})")
        op.execute(f"CREATE POLICY {prefix}_insert ON {table} FOR INSERT WITH CHECK ({writer} AND {row_visible})")
        op.execute(f"CREATE POLICY {prefix}_update ON {table} FOR UPDATE USING ({writer} AND {row_visible}) WITH CHECK ({writer} AND {row_visible})")
        op.execute(f"CREATE POLICY {prefix}_delete ON {table} FOR DELETE USING ({deleter} AND {row_visible})")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE SCHEMA korpus_auth")
    op.execute("REVOKE ALL ON SCHEMA korpus_auth FROM PUBLIC")
    op.execute("""
        CREATE TABLE korpus_auth.capability_keys (
            key_id text PRIMARY KEY,
            secret bytea NOT NULL CHECK (octet_length(secret) >= 32),
            enabled boolean NOT NULL DEFAULT true,
            not_before timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            CHECK (expires_at > not_before)
        )
    """)
    op.execute("""
        CREATE TABLE korpus_auth.consumed_capabilities (
            jti text PRIMARY KEY,
            key_id text NOT NULL REFERENCES korpus_auth.capability_keys(key_id),
            transaction_id bigint NOT NULL,
            expires_at timestamptz NOT NULL
        )
    """)
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA korpus_auth FROM PUBLIC")

    op.execute("""
        CREATE FUNCTION korpus_auth.verified_payload(token text) RETURNS jsonb
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, korpus_auth, public
        AS $$
        DECLARE
            encoded text;
            signature text;
            padding text;
            payload jsonb;
            signing_key korpus_auth.capability_keys%ROWTYPE;
        BEGIN
            IF token IS NULL OR length(token) < 66 OR length(token) > 8192
               OR token !~ '^[A-Za-z0-9_-]+\\.[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'DBCAP_INVALID_FORMAT' USING ERRCODE = '28000';
            END IF;
            encoded := split_part(token, '.', 1);
            signature := split_part(token, '.', 2);
            padding := repeat('=', (4 - length(encoded) % 4) % 4);
            BEGIN
                payload := convert_from(decode(translate(encoded, '-_', '+/') || padding, 'base64'), 'UTF8')::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'DBCAP_INVALID_PAYLOAD' USING ERRCODE = '28000';
            END;
            IF jsonb_typeof(payload) <> 'object'
               OR payload->>'aud' <> 'korpus-db'
               OR payload->>'v' <> '1'
               OR payload->>'key_id' IS NULL
               OR payload->>'jti' IS NULL
               OR length(payload->>'jti') NOT BETWEEN 1 AND 200
               OR jsonb_typeof(payload->'roles') <> 'array'
               OR jsonb_typeof(payload->'operations') <> 'array'
               OR jsonb_typeof(payload->'corpora') <> 'array'
               OR jsonb_typeof(payload->'classifications') <> 'array'
               OR jsonb_typeof(payload->'compartments') <> 'array' THEN
                RAISE EXCEPTION 'DBCAP_INVALID_CLAIMS' USING ERRCODE = '28000';
            END IF;
            SELECT * INTO signing_key FROM korpus_auth.capability_keys
             WHERE key_id = payload->>'key_id' AND enabled
               AND clock_timestamp() >= not_before AND clock_timestamp() < expires_at;
            IF NOT FOUND OR public.hmac(convert_to(encoded, 'UTF8'), signing_key.secret, 'sha256') <> decode(signature, 'hex') THEN
                RAISE EXCEPTION 'DBCAP_INVALID_SIGNATURE' USING ERRCODE = '28000';
            END IF;
            IF (payload->>'nbf')::bigint > extract(epoch FROM clock_timestamp())::bigint
               OR (payload->>'exp')::bigint <= extract(epoch FROM clock_timestamp())::bigint
               OR (payload->>'exp')::bigint - (payload->>'nbf')::bigint > 300 THEN
                RAISE EXCEPTION 'DBCAP_INVALID_LIFETIME' USING ERRCODE = '28000';
            END IF;
            IF (payload->>'clearance')::int NOT BETWEEN 0 AND 3 THEN
                RAISE EXCEPTION 'DBCAP_INVALID_CLEARANCE' USING ERRCODE = '28000';
            END IF;
            RETURN payload;
        EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
            RAISE EXCEPTION 'DBCAP_INVALID_CLAIMS' USING ERRCODE = '28000';
        END
        $$
    """)
    op.execute("""
        CREATE FUNCTION korpus_auth.activate(token text) RETURNS void
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER
        SET search_path = pg_catalog, korpus_auth, public
        AS $$
        DECLARE payload jsonb;
        BEGIN
            payload := korpus_auth.verified_payload(token);
            INSERT INTO korpus_auth.consumed_capabilities(jti, key_id, transaction_id, expires_at)
            VALUES (payload->>'jti', payload->>'key_id', txid_current(), to_timestamp((payload->>'exp')::bigint));
            PERFORM set_config('korpus.verified_capability', token, true);
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'DBCAP_REPLAYED' USING ERRCODE = '28000';
        END
        $$
    """)
    op.execute("""
        CREATE FUNCTION korpus_auth.claims() RETURNS jsonb
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, korpus_auth, public
        AS $$
        DECLARE payload jsonb;
        BEGIN
            IF COALESCE(current_setting('korpus.verified_capability', true), '') = '' THEN
                RETURN '{}'::jsonb;
            END IF;
            payload := korpus_auth.verified_payload(current_setting('korpus.verified_capability', true));
            IF NOT EXISTS (
                SELECT 1 FROM korpus_auth.consumed_capabilities
                WHERE jti=payload->>'jti' AND key_id=payload->>'key_id'
                  AND transaction_id=txid_current() AND expires_at > clock_timestamp()
            ) THEN
                RAISE EXCEPTION 'DBCAP_NOT_ACTIVE' USING ERRCODE = '28000';
            END IF;
            RETURN payload;
        END
        $$
    """)
    op.execute("""
        CREATE FUNCTION korpus_auth.claim_array(name text) RETURNS text[]
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, korpus_auth
        AS $$ SELECT COALESCE(array_agg(value ORDER BY value), ARRAY[]::text[])
              FROM jsonb_array_elements_text(korpus_auth.claims()->name) item(value) $$
    """)
    op.execute("""
        CREATE FUNCTION korpus_auth.has_role(expected text) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, korpus_auth
        AS $$ SELECT expected = ANY(korpus_auth.claim_array('roles')) $$
    """)
    op.execute("""
        CREATE FUNCTION korpus_auth.has_operation(expected text) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, korpus_auth
        AS $$ SELECT expected = ANY(korpus_auth.claim_array('operations')) $$
    """)
    op.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA korpus_auth FROM PUBLIC")
    _drop_current_policies()
    _create_capability_policies()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _drop_current_policies()
    roles = _legacy_roles()
    visible = _legacy_visible()
    writer = f"('admin'=ANY({roles}) OR 'curator'=ANY({roles}))"
    op.execute(f"CREATE POLICY document_select ON documents FOR SELECT USING ({visible})")
    op.execute(f"CREATE POLICY document_insert ON documents FOR INSERT WITH CHECK ({writer} AND {visible})")
    op.execute(f"CREATE POLICY document_update ON documents FOR UPDATE USING ({writer} AND {visible}) WITH CHECK ({writer} AND {visible})")
    op.execute(f"CREATE POLICY document_delete ON documents FOR DELETE USING ('admin'=ANY({roles}) AND {visible})")
    descendants = {
        "document_versions": ("version", "EXISTS (SELECT 1 FROM documents d WHERE d.id=document_versions.document_id)"),
        "evidence_spans": ("evidence_span", "EXISTS (SELECT 1 FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE v.id=evidence_spans.version_id)"),
        "span_embeddings": ("embedding", "EXISTS (SELECT 1 FROM evidence_spans s JOIN document_versions v ON v.id=s.version_id JOIN documents d ON d.id=v.document_id WHERE s.id=span_embeddings.span_id)"),
        "document_compartments": ("document_compartment", "EXISTS (SELECT 1 FROM documents d WHERE d.id=document_compartments.document_id)"),
    }
    for table, (prefix, row_visible) in descendants.items():
        op.execute(f"CREATE POLICY {prefix}_select ON {table} FOR SELECT USING ({row_visible})")
        op.execute(f"CREATE POLICY {prefix}_insert ON {table} FOR INSERT WITH CHECK ({writer} AND {row_visible})")
        op.execute(f"CREATE POLICY {prefix}_update ON {table} FOR UPDATE USING ({writer} AND {row_visible}) WITH CHECK ({writer} AND {row_visible})")
        op.execute(f"CREATE POLICY {prefix}_delete ON {table} FOR DELETE USING ('admin'=ANY({roles}) AND {row_visible})")
    op.execute("DROP SCHEMA korpus_auth CASCADE")
