from __future__ import annotations

from datetime import date
from pathlib import Path

from korpus.application.ingestion import ExtractionSettings
from korpus.application.policy import PolicyEngine
from korpus.composition import build_ingestion_service
from korpus.config import get_settings
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    DocumentCreate,
    Identity,
    ReviewState,
    ReviewTransition,
    VersionCreate,
)
from korpus.infrastructure.runtime import create_object_store, create_repository

#: The demonstration order's stated publication date. Fixed, so two bootstraps of the
#: same tree produce the same corpus.
BOOTSTRAP_PUBLICATION_DATE = date(2026, 1, 15)


def main() -> None:
    settings = get_settings()
    policy = PolicyEngine()
    repository = create_repository(settings, policy)
    repository.initialize()
    store = create_object_store(settings)
    actor = Identity(
        subject="bootstrap",
        roles=frozenset({"admin", "curator", "reviewer", "user", "auditor"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public", "training", "administrative", "restricted-demo"}),
    )
    service = build_ingestion_service(
        repository,
        store,
        policy,
        ExtractionSettings(
            ocr_enabled=settings.ocr_enabled,
            ocr_languages=settings.ocr_languages,
            max_pdf_pages=settings.max_pdf_pages,
            max_spans_per_document=settings.max_spans_per_document,
            max_chunk_chars=settings.max_chunk_chars,
            chunk_overlap_chars=settings.chunk_overlap_chars,
        ),
        review_separation_required=settings.review_separation_required,
    )
    fixture = Path("evals/fixtures/public_order.txt")
    result = service.ingest(
        actor,
        DocumentCreate(
            canonical_title="Демонстраційний порядок ведення журналу",
            corpus_id="public",
            issuer="KORPUS Demonstration Authority",
            document_type="demonstration_order",
        ),
        VersionCreate(
            revision="1.0",
            publication_identifier="DEMO-001",
            authority=AuthorityClass.OFFICIAL_UA,
            # Approval refuses a version that states neither effective_from nor
            # publication_date — without one it would govern every past date. This
            # script created neither and then approved, so `make bootstrap` had not
            # worked since that rule landed: the documented way to get a running local
            # instance failed at the last step (found 2026-08-06 by running it).
            #
            # A fixed date rather than today's: a bootstrap that seeds a different
            # corpus on every run cannot be compared against itself, and "which edition
            # was in force on date X" is the question this system answers.
            publication_date=BOOTSTRAP_PUBLICATION_DATE,
        ),
        fixture.name,
        "text/plain",
        fixture.read_bytes(),
    )
    if not result.duplicate:
        for state in (
            ReviewState.METADATA_REVIEWED,
            ReviewState.CONTENT_REVIEWED,
            ReviewState.APPROVED,
        ):
            service.transition(
                actor,
                result.version.id,
                ReviewTransition(target=state, note="bootstrap fixture review"),
            )
    print(f"database={settings.database_url}")
    print(f"document={result.document.id}")
    print(f"version={result.version.id}")
    print(f"release={repository.corpus_release_id(actor, actor.corpora, date.today())}")


if __name__ == "__main__":
    main()
