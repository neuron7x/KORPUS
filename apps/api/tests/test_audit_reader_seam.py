"""The audit read side split off; the chain still verifies against what the writer wrote.

COD-001 records `SqlRepository` as an infrastructure god object — forty-eight methods
over sixteen hundred lines. Most of it cannot be split without splitting a transaction:
`create_version_bundle` writes rows and their audit event atomically, and an
abstraction that separated them would break that atomicity or leak it.

Three methods do not share a transaction with any write. They are the seam the class
actually has, and these tests hold the two properties that make taking it safe.

The first is that the canonical form is shared. The writer computes an HMAC over it and
the verifier recomputes it; two copies would produce a chain that fails to verify events
it wrote itself, and nothing else in the system would notice until an audit.

The second is that the extraction is behaviour-preserving, which is only demonstrable
by writing through the repository and verifying through the reader.
"""

from __future__ import annotations

from pathlib import Path

from korpus.application.policy import PolicyEngine
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.audit_reader import audit_canonical
from korpus.infrastructure.repository import SqlRepository

WHO = Identity(
    subject="curator",
    roles=frozenset({"admin", "user", "auditor"}),
    clearance=AccessTier.RESTRICTED,
    corpora=frozenset({"public"}),
)


def _repository(tmp_path: Path) -> SqlRepository:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'seam.db'}",
        "seam-audit-key",
        PolicyEngine(),
        tmp_path / "anchor.json",
    )
    repository.initialize()
    return repository


def test_the_writer_and_the_verifier_share_one_canonical_form() -> None:
    """One definition, or the chain fails to verify events it produced itself."""
    assert SqlRepository._audit_canonical is audit_canonical


def test_events_written_through_the_repository_verify_through_the_reader(
    tmp_path: Path,
) -> None:
    """The extraction is behaviour-preserving only if this holds across the seam."""
    repository = _repository(tmp_path)
    for index in range(5):
        repository.append_audit(
            WHO, "document.ingested", "document_version", f"d{index}", {"i": index}
        )

    verification = repository.verify_audit()

    assert verification.valid is True
    assert verification.event_count == 5
    assert verification.head_sequence == 5


def test_a_tampered_event_is_caught_across_the_seam(tmp_path: Path) -> None:
    """The property the whole chain exists for, checked after the move rather than
    assumed to have survived it."""
    from sqlalchemy import text as sql_text

    repository = _repository(tmp_path)
    for index in range(3):
        repository.append_audit(
            WHO, "document.ingested", "document_version", f"d{index}", {"i": index}
        )

    with repository.engine.begin() as connection:
        connection.execute(
            sql_text("UPDATE audit_events SET actor_subject = 'someone-else' WHERE sequence = 2")
        )

    verification = repository.verify_audit()

    assert verification.valid is False
    assert verification.first_invalid_sequence == 2


def test_readiness_reports_the_schema_revision_the_migrations_declare(
    tmp_path: Path,
) -> None:
    """The expected revision is passed into the reader rather than imported there.

    A second copy would drift silently, which SCHEMA_REVISION already did once: it
    stayed at 0009 after 0010 shipped, and production would not start.
    """
    repository = _repository(tmp_path)

    snapshot = repository.readiness_snapshot(
        max_pending_events=64, max_pending_age_seconds=60.0
    )

    assert snapshot["expected_schema_revision"] == repository.schema_revision() or (
        snapshot["schema_revision"] is None
    )
    assert snapshot["schema_current"] is True
    assert set(snapshot) >= {
        "database",
        "audit_head_sequence",
        "anchor_gap_events",
        "pending_anchor_events",
        "ready",
    }


def test_the_reader_opens_its_own_connections(tmp_path: Path) -> None:
    """The seam exists because these methods share no transaction with a write.

    If one ever ran inside `_transaction_with_anchor`, extracting it would have changed
    when its reads became visible — and the tests above would still pass.
    """
    import inspect

    from korpus.infrastructure import audit_reader

    source = inspect.getsource(audit_reader.AuditReader)

    assert "_transaction_with_anchor" not in source
    assert source.count("self.engine.connect()") >= 3
