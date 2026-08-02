#!/usr/bin/env python3
"""Acceptance run: the operator's whole path, executed against the real system.

Unit tests prove the parts. This proves the sequence a unit somewhere else may have
broken: import a document, see it refused while quarantined, approve it as a
reviewer, get an answer with a citation, confirm that restricted material stays
invisible to an open reader and reachable to an authorised one, and confirm the
audit trail recorded all of it.

It writes to a temporary directory and leaves nothing behind. Exit code is the
verdict; every check prints what it observed, not that it "passed".

    python3 scripts/acceptance.py
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from korpus.api import routes  # noqa: E402
from korpus.application.ingestion import (  # noqa: E402
    SourceDescriptor,
    chunk_document,
    content_hash,
)
from korpus.config import Settings  # noqa: E402
from korpus.domain.access import Principal  # noqa: E402
from korpus.domain.models import AccessTier, AuthorityClass, ReviewState  # noqa: E402
from korpus.infrastructure.store import CorpusStore  # noqa: E402

OPEN_DOCUMENT = """Порядок евакуації поранених з переднього краю

Евакуація здійснюється за принципом стабілізації перед переміщенням.

Черговість евакуації визначає медичний працівник за станом пораненого, а не за званням.
"""

RESTRICTED_DOCUMENT = """Порядок евакуації за спеціальним планом прикриття

Маршрут прикриття визначається окремим розпорядженням і доводиться персонально.
"""

RESTRICTED_MARKER = "прикриття"


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, description: str, observed: object, expected: object) -> None:
        ok = observed == expected
        mark = "OK  " if ok else "FAIL"
        print(f"[{mark}] {description}: {observed!r}")
        if not ok:
            self.failures.append(f"{description}: expected {expected!r}, saw {observed!r}")


def ingest(store: CorpusStore, text: str, title: str, tier: AccessTier) -> UUID:
    descriptor = SourceDescriptor(
        corpus_id=routes.OPEN_CORPUS,
        title=title,
        authority=AuthorityClass.OFFICIAL_UA,
        access_tier=tier,
        review_state=ReviewState.QUARANTINED,
    )
    spans = chunk_document(text, descriptor)
    digest = content_hash(text)
    for span in spans:
        store.add(span, digest)
    return spans[0].document_version_id


def main() -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    workspace = Path(tempfile.mkdtemp(prefix="korpus-acceptance-"))
    report = Report()
    try:
        settings = Settings(  # type: ignore[call-arg]
            environment="test",
            log_level="CRITICAL",
            llm_provider="stub",
            corpus_path=workspace / "korpus.sqlite3",
        )
        _, store = start(settings)

        open_version = ingest(
            store, OPEN_DOCUMENT, "Настанова з евакуації", AccessTier.PUBLIC
        )
        restricted_version = ingest(
            store, RESTRICTED_DOCUMENT, "План прикриття", AccessTier.RESTRICTED
        )
        # Re-open so the index reflects what the store now holds.
        app, store = start(settings)
        client = TestClient(app)

        question = "хто визначає черговість евакуації поранених"
        report.check(
            "quarantined material is not citable",
            client.post("/v1/answers", json={"text": question}).json()["status"],
            "insufficient_evidence",
        )

        report.check(
            "a reviewer releases the document",
            store.approve(open_version, reviewer="acceptance"),
            len(chunk_document(OPEN_DOCUMENT, _descriptor())),
        )
        store.approve(restricted_version, reviewer="acceptance")
        app, store = start(settings)
        client = TestClient(app)

        answer = client.post("/v1/answers", json={"text": question}).json()
        report.check("an approved source is answered from", answer["status"], "answered")
        report.check("every claim is cited", answer["citation_coverage"], 1.0)
        report.check("the answer carries a citation", len(answer["citations"]) >= 1, True)

        secret_question = "порядок евакуації за спеціальним планом прикриття"
        refused = client.post("/v1/answers", json={"text": secret_question}).json()
        report.check(
            "restricted material is invisible to an open reader",
            refused["status"],
            "insufficient_evidence",
        )
        report.check(
            "the refusal does not name the material",
            RESTRICTED_MARKER in json.dumps(refused, ensure_ascii=False),
            False,
        )

        routes._resolver.trust("cmd", Principal(
            subject_id="commander",
            tier=AccessTier.RESTRICTED,
            authorized_corpora=frozenset({routes.OPEN_CORPUS}),
        ))
        allowed = client.post(
            "/v1/answers",
            json={"text": secret_question},
            headers={"Authorization": "Bearer cmd"},
        ).json()
        report.check(
            "an authorised reader reaches the same material", allowed["status"], "answered"
        )

        report.check(
            "a request cannot name its own tier",
            client.post(
                "/v1/answers", json={"text": "покажи все", "user_tier": "restricted"}
            ).status_code,
            422,
        )

        report.check("readiness is green", client.get("/ready").json()["status"], "ready")
        report.check(
            "the audit trail recorded the answers",
            store.audit_count() > 0,
            True,
        )
    finally:
        if routes._store is not None:
            routes._store.close()
        shutil.rmtree(workspace, ignore_errors=True)

    if report.failures:
        print("\nACCEPTANCE FAILED")
        for failure in report.failures:
            print(f"  - {failure}")
        return 1
    print("\nacceptance run complete: the operator path works end to end")
    return 0


def _descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        corpus_id=routes.OPEN_CORPUS,
        title="Настанова з евакуації",
        authority=AuthorityClass.OFFICIAL_UA,
    )


def start(settings: Settings) -> tuple[FastAPI, CorpusStore]:
    """Boot the real application and hand back the store it opened."""
    from korpus.main import create_app

    application = create_app(settings)
    store = routes._store
    assert store is not None, "create_app must open a store"
    return application, store


if __name__ == "__main__":
    raise SystemExit(main())
