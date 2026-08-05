"""Row shapes are two shapes, and collapsing them would hide that.

`document`/`version` read the base tables; `*_from_projection` read the retrieval
projection, which names the same fields differently because it joins. One function with
a flag would make a projection row and a table row look like one thing, and the next
column added would land in whichever branch its author happened to be reading.

The round-trips matter for the same reason the extraction was safe: a record written
through `*_values` and read back through the mapper must be the record that went in, or
the move changed behaviour in a way no repository test would show.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    ReviewState,
)
from korpus.infrastructure import row_mapping


def _document() -> DocumentRecord:
    return DocumentRecord(
        id=uuid4(),
        canonical_title="Наказ №7",
        corpus_id="public",
        issuer="Issuer",
        jurisdiction="UA",
        document_type="order",
        access_tier=AccessTier.RESTRICTED,
        classification=Classification.RESTRICTED,
        compartments=frozenset({"alpha"}),
        created_at=datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
    )


def test_a_document_survives_the_round_trip() -> None:
    """Written through `document_values`, read back through `document`."""
    original = _document()

    restored = row_mapping.document(row_mapping.document_values(original))

    assert restored == original


def test_compartments_survive_as_a_set_not_a_string() -> None:
    """They are stored as JSON; a mapper that returned the raw text would compare equal
    to nothing and silently deny every compartmented request."""
    original = _document()

    restored = row_mapping.document(row_mapping.document_values(original))

    assert restored.compartments == frozenset({"alpha"})


def test_the_projection_mapper_reads_the_joined_column_names() -> None:
    """`document_id`, not `id` — the projection joins, so the key differs."""
    original = _document()
    values = row_mapping.document_values(original)
    projection = {
        **values,
        "document_id": values["id"],
        "document_created_at": values["created_at"],
    }
    del projection["id"]

    assert row_mapping.document_from_projection(projection) == original


def test_the_base_mapper_refuses_a_projection_row() -> None:
    """The two shapes are different, and the failure must be loud rather than partial."""
    original = _document()
    values = row_mapping.document_values(original)
    projection = {
        **values,
        "document_id": values["id"],
        "document_created_at": values["created_at"],
    }
    del projection["id"]

    with pytest.raises(KeyError):
        row_mapping.document(projection)


@pytest.mark.parametrize(
    "clearance,expected",
    [
        (AccessTier.PUBLIC, ["public"]),
        (AccessTier.AUTHENTICATED, ["public", "internal"]),
        (AccessTier.RESTRICTED, ["public", "internal", "restricted"]),
    ],
)
def test_clearance_widens_the_classifications_it_may_read(clearance, expected) -> None:
    """Monotone by construction: a higher clearance never sees less."""
    assert row_mapping.allowed_classifications(clearance) == expected


def test_a_naive_timestamp_is_read_as_utc() -> None:
    """SQLite returns naive datetimes; comparing one to an aware value raises."""
    assert row_mapping.iso(datetime(2026, 8, 5, 12, 0)).endswith("+00:00")


def test_an_aware_timestamp_keeps_its_offset() -> None:
    assert row_mapping.iso(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)) == "2026-08-05T12:00:00+00:00"


def test_the_repository_uses_these_functions_rather_than_copies() -> None:
    """Two definitions of a row shape drift, and the drift shows up as a field that is
    silently absent from one code path."""
    from korpus.infrastructure.repository import SqlRepository

    assert SqlRepository._document is row_mapping.document
    assert SqlRepository._version is row_mapping.version
    assert SqlRepository._span_from_projection is row_mapping.span_from_projection


def test_review_state_and_authority_come_back_as_enums() -> None:
    """A version whose review state is the string "approved" compares unequal to
    ReviewState.APPROVED, and every gate keyed on that comparison silently opens."""
    from korpus.domain.models import DocumentVersionRecord

    version = DocumentVersionRecord(
        document_id=uuid4(),
        revision="1",
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.APPROVED,
        source_hash="a" * 64,
        object_key="ab/cd/" + "a" * 64,
        mime_type="text/plain",
        byte_size=10,
        content_fingerprint="0" * 16,
    )

    restored = row_mapping.version(row_mapping.version_values(version))

    assert restored.review_state is ReviewState.APPROVED
    assert restored.authority is AuthorityClass.OFFICIAL_UA
