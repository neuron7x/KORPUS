"""Subject-title candidates must use canonical visibility before consuming top-K."""

from __future__ import annotations

from datetime import date

from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.retrieval_subject_query import subject_span_query
from sqlalchemy import create_engine, text

AS_OF = date(2026, 11, 6)
READER = Identity(
    subject="subject-candidate-reader",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public"}),
    compartments=frozenset({"alpha"}),
)
DDL = (
    "CREATE TABLE documents(id TEXT PRIMARY KEY,canonical_title TEXT,corpus_id TEXT,"
    "access_tier INTEGER,classification TEXT)",
    "CREATE TABLE document_compartments(document_id TEXT,compartment TEXT)",
    "CREATE TABLE document_versions(id TEXT PRIMARY KEY,document_id TEXT,"
    "review_state TEXT,effective_from TEXT,publication_date TEXT,effective_until TEXT,"
    "rescinded_at TEXT,supersedes_version_id TEXT)",
    "CREATE TABLE evidence_spans(id TEXT PRIMARY KEY,version_id TEXT,ordinal INTEGER)",
)


def _doc(conn, name: str, *, compartment: str | None = None, title: str = "Обовязки: ціль"):
    conn.execute(
        text("INSERT INTO documents VALUES(:name,:title,'public',0,'public')"),
        {"name": name, "title": title},
    )
    if compartment:
        conn.execute(
            text("INSERT INTO document_compartments VALUES(:doc,:compartment)"),
            {"doc": name, "compartment": compartment},
        )


def _version(conn, version: str, doc: str, *, publication: str = "2026-01-01", supersedes=None):
    conn.execute(
        text("INSERT INTO document_versions VALUES(:v,:d,'approved',NULL,:p,NULL,NULL,:s)"),
        {"v": version, "d": doc, "p": publication, "s": supersedes},
    )


def _span(conn, span: str, version: str):
    conn.execute(text("INSERT INTO evidence_spans VALUES(:s,:v,1)"), {"s": span, "v": version})


def _candidates(conn, *, limit=1):
    built = subject_span_query(READER, frozenset({"public"}), AS_OF, ["Обовязки: ціль"], limit)
    assert built is not None
    statement, parameters = built
    return [str(row.span_id) for row in conn.execute(statement, parameters)]


def test_subject_path_rejects_cross_document_supersession():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            for ddl in DDL:
                conn.execute(text(ddl))
            _doc(conn, "victim")
            _doc(conn, "foreign", title="unrelated")
            _version(conn, "v-victim", "victim")
            _version(conn, "v-foreign", "foreign", supersedes="v-victim")
            _span(conn, "z-visible", "v-victim")
            assert _candidates(conn) == ["z-visible"]
    finally:
        engine.dispose()


def test_subject_path_future_supersession_does_not_hide_current_version():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            for ddl in DDL:
                conn.execute(text(ddl))
            _doc(conn, "victim")
            _version(conn, "v-now", "victim")
            _version(conn, "v-future", "victim", publication="2027-01-01", supersedes="v-now")
            _span(conn, "z-visible", "v-now")
            assert _candidates(conn) == ["z-visible"]
    finally:
        engine.dispose()


def test_subject_path_compartment_filter_precedes_limit_with_positive_control():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            for ddl in DDL:
                conn.execute(text(ddl))
            _doc(conn, "hidden", compartment="bravo")
            _doc(conn, "visible", compartment="alpha")
            _version(conn, "v-hidden", "hidden")
            _version(conn, "v-visible", "visible")
            _span(conn, "a-hidden", "v-hidden")
            _span(conn, "z-visible", "v-visible")
            assert _candidates(conn) == ["z-visible"]
    finally:
        engine.dispose()
