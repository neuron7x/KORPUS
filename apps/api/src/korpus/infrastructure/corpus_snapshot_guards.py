"""Structural and semantic verification for database-owned temporal snapshot guards."""

from __future__ import annotations

import re

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Connection

EPOCH_TABLES = (
    "documents",
    "document_compartments",
    "document_versions",
    "evidence_spans",
    "span_embeddings",
)

_POSTGRES_FUNCTION_BODIES = {
    "korpus_bump_corpus_state_epoch": """
        BEGIN
          UPDATE public.corpus_state_epoch SET epoch = epoch + 1 WHERE singleton_id = 1;
          RETURN NULL;
        END;
    """,
    "korpus_refuse_approved_evidence_mutation": """
        DECLARE
          locked_digest text;
        BEGIN
          IF TG_OP = 'INSERT' THEN
            SELECT evidence_digest INTO locked_digest
            FROM public.document_versions
            WHERE id = NEW.version_id
            FOR SHARE;
            IF locked_digest IS NOT NULL THEN
              RAISE EXCEPTION 'sealed evidence is immutable';
            END IF;
          ELSIF TG_OP = 'DELETE' THEN
            SELECT evidence_digest INTO locked_digest
            FROM public.document_versions
            WHERE id = OLD.version_id
            FOR SHARE;
            IF locked_digest IS NOT NULL THEN
              RAISE EXCEPTION 'sealed evidence is immutable';
            END IF;
          ELSE
            FOR locked_digest IN
              SELECT evidence_digest
              FROM public.document_versions
              WHERE id IN (OLD.version_id, NEW.version_id)
              ORDER BY id
              FOR SHARE
            LOOP
              IF locked_digest IS NOT NULL THEN
                RAISE EXCEPTION 'sealed evidence is immutable';
              END IF;
            END LOOP;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
    """,
    "korpus_refuse_approved_digest_mutation": """
        BEGIN
          IF OLD.evidence_digest IS NOT NULL
             AND NEW.evidence_digest IS DISTINCT FROM OLD.evidence_digest THEN
            RAISE EXCEPTION 'sealed evidence digest is immutable';
          END IF;
          RETURN NEW;
        END;
    """,
}


def _normalize(definition: object) -> str:
    return " ".join(str(definition or "").lower().split())


def _canonical_function_body(definition: object) -> str:
    source = str(definition or "")
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    source = re.sub(r"--[^\n]*", " ", source)
    return _normalize(source)


def _assert_definition(label: str, definition: str, required: tuple[str, ...]) -> None:
    missing = [token for token in required if token not in definition]
    if missing:
        raise RuntimeError(f"corpus snapshot guard {label} has invalid definition: {missing}")


def _assert_exact_function_body(label: str, body: object, expected: str) -> None:
    if _canonical_function_body(body) != _canonical_function_body(expected):
        raise RuntimeError(f"corpus snapshot guard {label} has invalid function body")


def _sqlite_guards(connection: Connection) -> None:
    rows = connection.execute(
        sql_text("SELECT tbl_name, name, sql FROM sqlite_master WHERE type = 'trigger'")
    ).all()
    actual = {(str(row[0]), str(row[1])): _normalize(row[2]) for row in rows}
    expected = {
        *(
            (table, f"trg_{table}_epoch_{operation}")
            for table in EPOCH_TABLES
            for operation in ("insert", "update", "delete")
        ),
        ("evidence_spans", "trg_evidence_spans_immutable_insert"),
        ("evidence_spans", "trg_evidence_spans_immutable_update"),
        ("evidence_spans", "trg_evidence_spans_immutable_delete"),
        ("document_versions", "trg_approved_version_digest_immutable"),
    }
    missing = expected.difference(actual)
    if missing:
        raise RuntimeError(f"corpus snapshot guards are missing: {sorted(missing)}")

    for table in EPOCH_TABLES:
        for operation in ("insert", "update", "delete"):
            key = (table, f"trg_{table}_epoch_{operation}")
            _assert_definition(
                key[1],
                actual[key],
                (
                    f"after {operation} on {table}",
                    "update corpus_state_epoch set epoch = epoch + 1 where singleton_id = 1",
                ),
            )
    for operation in ("insert", "update", "delete"):
        key = ("evidence_spans", f"trg_evidence_spans_immutable_{operation}")
        _assert_definition(
            key[1],
            actual[key],
            (
                f"before {operation} on evidence_spans",
                "evidence_digest is not null",
                "raise(abort, 'sealed evidence is immutable')",
            ),
        )
    key = ("document_versions", "trg_approved_version_digest_immutable")
    _assert_definition(
        key[1],
        actual[key],
        (
            "before update of evidence_digest on document_versions",
            "old.evidence_digest is not null",
            "raise(abort, 'sealed evidence digest is immutable')",
        ),
    )


def _postgres_guards(connection: Connection) -> None:
    rows = connection.execute(
        sql_text(
            "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid) "
            "FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE NOT t.tgisinternal AND n.nspname = 'public'"
        )
    ).all()
    actual = {(str(row[0]), str(row[1])): _normalize(row[2]) for row in rows}
    expected = {
        *((table, f"trg_{table}_epoch") for table in EPOCH_TABLES),
        ("evidence_spans", "trg_evidence_spans_immutable"),
        ("document_versions", "trg_approved_version_digest_immutable"),
    }
    missing = expected.difference(actual)
    if missing:
        raise RuntimeError(f"corpus snapshot guards are missing: {sorted(missing)}")

    for table in EPOCH_TABLES:
        key = (table, f"trg_{table}_epoch")
        _assert_definition(
            key[1],
            actual[key],
            (
                "after",
                "insert",
                "update",
                "delete",
                f"on public.{table}",
                "korpus_bump_corpus_state_epoch",
            ),
        )
    _assert_definition(
        "trg_evidence_spans_immutable",
        actual[("evidence_spans", "trg_evidence_spans_immutable")],
        (
            "before",
            "insert",
            "update",
            "delete",
            "on public.evidence_spans",
            "korpus_refuse_approved_evidence_mutation",
        ),
    )
    _assert_definition(
        "trg_approved_version_digest_immutable",
        actual[("document_versions", "trg_approved_version_digest_immutable")],
        (
            "before update",
            "on public.document_versions",
            "korpus_refuse_approved_digest_mutation",
        ),
    )

    functions = {
        str(row[0]): (bool(row[1]), tuple(row[2] or ()), row[3])
        for row in connection.execute(
            sql_text(
                "SELECT p.proname, p.prosecdef, p.proconfig, p.prosrc "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' AND p.pronargs = 0 "
                "AND p.prorettype = 'trigger'::regtype AND p.proname IN "
                "('korpus_bump_corpus_state_epoch', "
                "'korpus_refuse_approved_evidence_mutation', "
                "'korpus_refuse_approved_digest_mutation')"
            )
        ).all()
    }
    for name in (
        "korpus_bump_corpus_state_epoch",
        "korpus_refuse_approved_evidence_mutation",
    ):
        metadata = functions.get(name)
        if metadata is None:
            raise RuntimeError(f"corpus snapshot guard function is missing: {name}")
        security_definer, configuration, _body = metadata
        normalized_config = {item.replace(" ", "").lower() for item in configuration}
        if not security_definer or "search_path=pg_catalog" not in normalized_config:
            raise RuntimeError(f"corpus snapshot guard function is not hardened: {name}")

    for name, expected_body in _POSTGRES_FUNCTION_BODIES.items():
        metadata = functions.get(name)
        if metadata is None:
            raise RuntimeError(f"corpus snapshot guard function is missing: {name}")
        _security_definer, _configuration, body = metadata
        _assert_exact_function_body(name, body, expected_body)


def require_guards(connection: Connection) -> None:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        _sqlite_guards(connection)
        return
    if dialect == "postgresql":
        _postgres_guards(connection)
        return
    raise RuntimeError(f"unsupported corpus snapshot dialect: {dialect}")
