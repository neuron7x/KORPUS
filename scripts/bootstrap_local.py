from __future__ import annotations

from pathlib import Path

from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.policy import PolicyEngine
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
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.repository import SqlRepository


def main() -> None:
    settings = get_settings()
    policy = PolicyEngine()
    repository = SqlRepository(settings.database_url, settings.resolved_audit_hmac_key, policy)
    repository.initialize()
    store = LocalObjectStore(settings.object_root)
    actor = Identity(
        subject="bootstrap",
        roles=frozenset({"admin", "curator", "reviewer", "user", "auditor"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public", "training", "administrative", "restricted-demo"}),
    )
    service = IngestionService(
        repository,
        store,
        policy,
        ExtractionSettings(settings.ocr_enabled, settings.ocr_languages),
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
        VersionCreate(revision="1.0", publication_identifier="DEMO-001", authority=AuthorityClass.OFFICIAL_UA),
        fixture.name,
        "text/plain",
        fixture.read_bytes(),
    )
    if not result.duplicate:
        for state in (ReviewState.METADATA_REVIEWED, ReviewState.CONTENT_REVIEWED, ReviewState.APPROVED):
            service.transition(actor, result.version.id, ReviewTransition(target=state, note="bootstrap fixture review"))
    print(f"database={settings.database_url}")
    print(f"document={result.document.id}")
    print(f"version={result.version.id}")
    print(f"release={repository.corpus_release_id()}")


if __name__ == "__main__":
    main()
