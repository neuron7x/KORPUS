"""Where the layers are wired together, and the only place that knows both sides.

`application` states what it needs as protocols in `application/ports.py`;
`infrastructure` provides the implementations. Something has to name both, and that
something is a composition root rather than either layer — otherwise the dependency
runs backwards and the application cannot be imported, reasoned about or tested without
a parser, a database and an object store present.

This module exists because the alternative kept reappearing as a default argument. A
default has to name an implementation, and every way of naming one — an import at module
scope, a deferred import inside `__init__` — puts the edge back into the import graph
that `test_architecture.py` reads.
"""

from __future__ import annotations

from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.policy import PolicyEngine
from korpus.application.ports import Extractor, ObjectStore, Repository
from korpus.infrastructure.extraction import DocumentExtractor
from korpus.security.corpus_governance import CorpusGovernanceProfile
from korpus.security.reviewers import ReviewerRegistry
from korpus.security.scanning import MalwareScanner
from korpus.security.source_authenticity import SourceTrustProfile


def default_extractor() -> Extractor:
    """The parsing adapter every caller gets unless it says otherwise."""
    return DocumentExtractor()


def build_ingestion_service(
    repository: Repository,
    object_store: ObjectStore,
    policy: PolicyEngine,
    extraction: ExtractionSettings,
    *,
    extractor: Extractor | None = None,
    review_separation_required: bool = False,
    malware_scanner: MalwareScanner | None = None,
    source_trust_profile: SourceTrustProfile | None = None,
    require_source_signature: bool = False,
    reviewer_registry: ReviewerRegistry | None = None,
    require_reviewer_credentials: bool = False,
    corpus_governance: CorpusGovernanceProfile | None = None,
    require_corpus_governance: bool = False,
) -> IngestionService:
    """`IngestionService` with the infrastructure adapters filled in.

    Callers that need a different extractor — a test asserting which parser path a
    setting selects, a worker with its own sandbox policy — pass one. Nobody has to
    reach into `korpus.infrastructure` to get the ordinary case.
    """
    return IngestionService(
        repository,
        object_store,
        policy,
        extraction,
        review_separation_required=review_separation_required,
        malware_scanner=malware_scanner,
        source_trust_profile=source_trust_profile,
        require_source_signature=require_source_signature,
        reviewer_registry=reviewer_registry,
        require_reviewer_credentials=require_reviewer_credentials,
        corpus_governance=corpus_governance,
        require_corpus_governance=require_corpus_governance,
        extractor=extractor if extractor is not None else default_extractor(),
    )
