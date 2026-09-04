"""The physical schema, apart from everything that reads or writes it.

COD-001 names six responsibilities inside `SqlRepository`: "schema, CRUD, search, audit,
readiness, RLS context". This is the first of them, and it is the one that had the least
reason to be there — a table definition is a declaration, not behaviour, and nothing here
runs at request time.

Keeping it here also gives the retrieval query builders somewhere to import from without
a cycle back through the repository that calls them.

Every name is re-exported from `repository` so existing call sites and the mutation
catalogue keep working; a rename would be a second change riding on a move that is meant
to preserve behaviour exactly.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from korpus.application.keyring import LEGACY_KEY_ID

#: The alembic head this code expects. `initialize(create_schema=False)` — the
#: production path — refuses to start on anything else. It is pinned by
#: test_schema_revision_pin.py against the migration graph, because it drifted once:
#: 0010 shipped, the constant stayed at 0009, and a migrated PostgreSQL database
#: refused to start while every SQLite test stayed green.
SCHEMA_REVISION = "0023_evidence_search_vector"

metadata = MetaData()

#: Лічильник стану корпусу — основа знімка читання для ОДНІЄЇ відповіді.
#:
#: Канон пінить корпус ДАТОЮ `as_of` і робить кілька незалежних читань на одну відповідь,
#: тож між ними схвалення чи скасування документа може змінити те, що читач бачить.
#: Епоха дає монотонний маркер, за яким `corpus_snapshot` бере узгоджений зріз.
corpus_state_epoch = Table(
    "corpus_state_epoch",
    metadata,
    Column("singleton_id", Integer, primary_key=True),
    Column("epoch", BigInteger, nullable=False, default=0),
    CheckConstraint("singleton_id = 1", name="ck_corpus_state_epoch_singleton"),
    CheckConstraint("epoch >= 0", name="ck_corpus_state_epoch_nonnegative"),
)


documents = Table(
    "documents",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("canonical_title", String(500), nullable=False),
    Column("corpus_id", String(64), nullable=False, index=True),
    Column("issuer", String(300), nullable=False),
    Column("jurisdiction", String(50), nullable=False),
    Column("document_type", String(100), nullable=False),
    Column("access_tier", Integer, nullable=False),
    Column("classification", String(32), nullable=False),
    Column("compartments_json", Text, nullable=False, default="[]"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("access_tier >= 0 AND access_tier <= 3", name="ck_document_access_tier"),
)

document_compartments = Table(
    "document_compartments",
    metadata,
    Column(
        "document_id",
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("compartment", String(64), primary_key=True),
)

versions = Table(
    "document_versions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column(
        "document_id",
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("revision", String(120), nullable=False),
    Column("publication_identifier", String(200)),
    Column("source_uri", Text),
    Column("source_hash", String(64), nullable=False, index=True),
    #: Дайджест ЗАПЕЧАТАНОГО набору доказів версії. `source_hash` каже, з чого версію
    #: зробили; цей — що саме затвердили. Портовано з GitHub-лінії разом із
    #: `evidence_sealing`: без нього схвалення не має чого прив'язати до себе.
    Column("evidence_digest", String(64)),
    Column("object_key", Text, nullable=False),
    Column("mime_type", String(200), nullable=False),
    Column("publication_date", Date),
    Column("effective_from", Date),
    Column("effective_until", Date),
    Column("rescinded_at", DateTime(timezone=True)),
    Column("authority", String(64), nullable=False),
    Column("source_key_id", String(200)),
    Column("source_signature_b64", Text),
    Column(
        "content_fingerprint",
        String(16),
        nullable=False,
        default="0000000000000000",
        index=True,
    ),
    Column("near_duplicate_of_version_id", String(36), ForeignKey("document_versions.id")),
    Column("near_duplicate_similarity", Float),
    Column("near_duplicate_acknowledged_by", String(200)),
    Column("extraction_text_chars", Integer, nullable=False, default=0),
    Column("extraction_alnum_ratio", Float, nullable=False, default=0.0),
    Column("extraction_replacement_ratio", Float, nullable=False, default=0.0),
    Column("extraction_quality_flags_json", Text, nullable=False, default="[]"),
    Column("extraction_quality_acknowledged_by", String(200)),
    Column("review_state", String(64), nullable=False),
    Column("supersedes_version_id", String(36), ForeignKey("document_versions.id")),
    Column("state_version", Integer, nullable=False, default=0),
    Column("metadata_reviewed_by", String(200)),
    Column("metadata_reviewer_credential_id", String(200)),
    Column("content_reviewed_by", String(200)),
    Column("content_reviewer_credential_id", String(200)),
    Column("approved_at", DateTime(timezone=True)),
    Column("approved_by", String(200)),
    Column("approver_credential_id", String(200)),
    Column("is_current", Boolean, nullable=False, default=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("document_id", "revision", name="uq_version_document_revision"),
    CheckConstraint("state_version >= 0", name="ck_version_state_version"),
    CheckConstraint(
        "effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from",
        name="ck_version_effective_window",
    ),
    CheckConstraint(
        "NOT is_current OR review_state = 'approved'", name="ck_version_current_approved"
    ),
)

Index(
    "uq_current_version_per_document",
    versions.c.document_id,
    unique=True,
    sqlite_where=versions.c.is_current.is_(True),
    postgresql_where=versions.c.is_current.is_(True),
)
Index(
    "ix_document_versions_validity",
    versions.c.document_id,
    versions.c.review_state,
    versions.c.effective_from,
    versions.c.effective_until,
)

spans = Table(
    "evidence_spans",
    metadata,
    Column("id", String(36), primary_key=True),
    Column(
        "version_id",
        String(36),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("ordinal", Integer, nullable=False),
    Column("page", Integer),
    Column("section", String(500)),
    Column("text", Text, nullable=False),
    Column("text_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("version_id", "ordinal", name="uq_span_version_ordinal"),
)

span_embeddings = Table(
    "span_embeddings",
    metadata,
    Column(
        "span_id",
        String(36),
        ForeignKey("evidence_spans.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("model_id", String(200), primary_key=True),
    Column("dimensions", Integer, nullable=False),
    Column("embedding_json", Text, nullable=False),
    Column("text_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("dimensions > 0", name="ck_span_embedding_dimensions"),
)

audits = Table(
    "audit_events",
    metadata,
    Column("sequence", BigInteger, primary_key=True),
    Column("event_id", String(36), nullable=False, unique=True),
    Column("event_schema_version", Integer, nullable=False, default=1),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("actor_subject", String(200), nullable=False),
    Column("action", String(200), nullable=False),
    Column("resource_type", String(100), nullable=False),
    Column("resource_id", String(200)),
    Column("payload_json", Text, nullable=False),
    Column("previous_hash", String(64), nullable=False),
    Column("event_hash", String(64), nullable=False),
    # Which key signed this. Without it, rotating the audit key invalidates every event
    # ever written, because the verifier recomputes each HMAC with whatever key the
    # process is holding. See korpus.application.keyring.
    Column("audit_key_id", String(64), nullable=False, server_default=LEGACY_KEY_ID),
)

audit_anchor_outbox = Table(
    "audit_anchor_outbox",
    metadata,
    Column(
        "sequence",
        BigInteger,
        ForeignKey("audit_events.sequence", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("head_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("delivered_at", DateTime(timezone=True)),
)

audit_heads = Table(
    "audit_heads",
    metadata,
    Column("singleton_id", Integer, primary_key=True),
    Column("sequence", BigInteger, nullable=False),
    Column("head_hash", String(64), nullable=False),
    CheckConstraint("singleton_id = 1", name="ck_audit_head_singleton"),
)

Index(
    "ix_audit_anchor_outbox_pending",
    audit_anchor_outbox.c.delivered_at,
    audit_anchor_outbox.c.created_at,
    audit_anchor_outbox.c.sequence,
)
