"""Structural and semantic verification for database-owned temporal snapshot guards."""

from __future__ import annotations

import re
from itertools import product

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Connection

from korpus.infrastructure.corpus_snapshot_guard_bodies import (
    POSTGRES_FUNCTION_BODIES as _POSTGRES_FUNCTION_BODIES,
)
from korpus.infrastructure.corpus_snapshot_sealed_guards import require_sealed_guards

EPOCH_TABLES = (
    "documents",
    "document_compartments",
    "document_versions",
    "evidence_spans",
    "span_embeddings",
)


def _normalize(definition: object) -> str:
    return " ".join(str(definition or "").lower().split())


def _canonical_function_body(definition: object) -> str:
    source = str(definition or "")
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    source = re.sub(r"--[^\n]*", " ", source)
    return _normalize(source)


def _assert_definition(label: str, definition: object, required: tuple[str, ...]) -> None:
    if isinstance(definition, tuple) and definition[1:] != ("public", required[-1]):
        raise RuntimeError(f"corpus snapshot guard {label} has invalid function binding")
    definition = str(definition[0] if isinstance(definition, tuple) else definition)
    header = definition.split(" begin ", 1)[0]
    if ("_epoch" in label or " on public." in header) and re.search(r"/\*|--|\bwhen\b", header):
        raise RuntimeError(f"corpus snapshot guard {label} has conditional trigger definition")
    if "_epoch" in label and re.search(r"\bupdate\s+of\b", header, flags=re.IGNORECASE):
        raise RuntimeError(f"corpus snapshot guard {label} has column-specific UPDATE trigger")
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
    expected_guards = {
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
    missing = expected_guards.difference(actual)
    if missing:
        raise RuntimeError(f"corpus snapshot guards are missing: {sorted(missing)}")
    for table, operation in product(EPOCH_TABLES, ("insert", "update", "delete")):
        key = (table, f"trg_{table}_epoch_{operation}")
        expected_sql = (
            f"create trigger {key[1]} after {operation} on {table} begin "
            "update corpus_state_epoch set epoch = epoch + 1 where singleton_id = 1; end"
        )
        if actual[key] != expected_sql:
            reason = "conditional trigger" if " when " in actual[key] else "invalid definition"
            raise RuntimeError(f"corpus snapshot guard {key[1]} has {reason}")
    for operation in ("insert", "update", "delete"):
        key = ("evidence_spans", f"trg_evidence_spans_immutable_{operation}")
        predicate = f"id = {'new' if operation == 'insert' else 'old'}.version_id"
        if operation == "update":
            predicate = "id in (old.version_id, new.version_id)"
        expected = (
            f"create trigger {key[1]} before {operation} on evidence_spans "
            "when exists (select 1 from document_versions "
            f"where {predicate} and evidence_digest is not null) "
            "begin select raise(abort, 'sealed evidence is immutable'); end"
        )
        if actual[key] != expected:
            raise RuntimeError(f"corpus snapshot guard {key[1]} has invalid definition")
    key = ("document_versions", "trg_approved_version_digest_immutable")
    expected = (
        "create trigger trg_approved_version_digest_immutable before update of evidence_digest "
        "on document_versions when old.evidence_digest is not null and "
        "new.evidence_digest is not old.evidence_digest begin "
        "select raise(abort, 'sealed evidence digest is immutable'); end"
    )
    if actual[key] != expected:
        raise RuntimeError(f"corpus snapshot guard {key[1]} has invalid definition")


def _postgres_guards(connection: Connection) -> None:
    rows = connection.execute(
        sql_text(
            "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid), fn.nspname, p.proname "
            "FROM pg_trigger t "
            "JOIN pg_proc p ON p.oid = t.tgfoid JOIN pg_namespace fn ON fn.oid = p.pronamespace "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE NOT t.tgisinternal AND t.tgenabled IN ('O', 'A') AND n.nspname = 'public'"
        )
    ).all()
    actual = {(str(r[0]), str(r[1])): (_normalize(r[2]), str(r[3]), str(r[4])) for r in rows}
    expected = {
        **{(t, f"trg_{t}_epoch"): "korpus_bump_corpus_state_epoch" for t in EPOCH_TABLES},
        ("evidence_spans", "trg_evidence_spans_immutable"): (
            "korpus_refuse_approved_evidence_mutation"
        ),
        ("document_versions", "trg_approved_version_digest_immutable"): (
            "korpus_refuse_approved_digest_mutation"
        ),
    }
    missing = expected.keys() - actual.keys()
    if missing:
        raise RuntimeError(f"corpus snapshot guards are missing: {sorted(missing)}")
    epoch_events = ("after", "insert", "update", "delete")
    for table in EPOCH_TABLES:
        key = (table, f"trg_{table}_epoch")
        _assert_definition(
            key[1],
            actual[key],
            (*epoch_events, f"on public.{table}", "korpus_bump_corpus_state_epoch"),
        )
    _assert_definition(
        "trg_evidence_spans_immutable",
        actual[("evidence_spans", "trg_evidence_spans_immutable")],
        (
            "before",
            "insert",
            "update",
            "delete",
            "on public.evidence_spans for each row",
            "korpus_refuse_approved_evidence_mutation",
        ),
    )
    _assert_definition(
        "trg_approved_version_digest_immutable",
        actual[("document_versions", "trg_approved_version_digest_immutable")],
        (
            "before update of evidence_digest",
            "on public.document_versions for each row",
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
    if connection.dialect.name == "sqlite":
        _sqlite_guards(connection)
    elif connection.dialect.name == "postgresql":
        _postgres_guards(connection)
    else:
        raise RuntimeError(f"unsupported corpus snapshot dialect: {connection.dialect.name}")
    require_sealed_guards(connection)
