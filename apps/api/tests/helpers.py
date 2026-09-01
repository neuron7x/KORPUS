from __future__ import annotations

import json
from datetime import date

from fastapi.testclient import TestClient
from korpus.application.corpus_snapshot import CorpusConsistencyError, CorpusReadToken


def ingest_text(
    client: TestClient,
    *,
    title: str = "Тестовий статут",
    corpus_id: str = "public",
    access_tier: int = 0,
    classification: str | None = None,
    authority: str = "official_ua",
    revision: str = "1.0",
    effective_from: date | None = None,
    effective_until: date | None = None,
    # An approved version must state when it starts to govern (see
    # test_currency_lower_bound.py); fixtures that do not care about dates get a
    # date in the past, and the tests that do care pass their own or None.
    publication_date: date | None = date(2020, 1, 1),
    text: str = (
        "Підрозділ веде журнал перевірок. Кожен запис має містити дату та відповідальну особу."
    ),
) -> dict[str, object]:
    version: dict[str, object] = {
        "revision": revision,
        "publication_identifier": f"TEST-{revision}",
        "authority": authority,
    }
    if effective_from is not None:
        version["effective_from"] = effective_from.isoformat()
    if effective_until is not None:
        version["effective_until"] = effective_until.isoformat()
    if publication_date is not None:
        version["publication_date"] = publication_date.isoformat()
    response = client.post(
        "/v1/documents/ingest",
        data={
            "document_json": json.dumps(
                {
                    "canonical_title": title,
                    "corpus_id": corpus_id,
                    "issuer": "Authorized Test Authority",
                    "jurisdiction": "UA",
                    "document_type": "order",
                    "access_tier": access_tier,
                    "classification": classification
                    or ("public" if access_tier == 0 else "restricted"),
                }
            ),
            "version_json": json.dumps(version),
        },
        files={"file": ("document.txt", text.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 201, response.text
    payload: dict[str, object] = response.json()
    return payload


def ingest_version(
    client: TestClient,
    document_id: str,
    *,
    revision: str,
    text: str,
    supersedes_version_id: str | None = None,
    effective_from: date | None = None,
    publication_date: date | None = date(2020, 1, 1),
) -> dict[str, object]:
    version: dict[str, object] = {"revision": revision, "authority": "official_ua"}
    if publication_date is not None:
        version["publication_date"] = publication_date.isoformat()
    if supersedes_version_id is not None:
        version["supersedes_version_id"] = supersedes_version_id
    if effective_from is not None:
        version["effective_from"] = effective_from.isoformat()
    response = client.post(
        f"/v1/documents/{document_id}/versions/ingest",
        data={"version_json": json.dumps(version)},
        files={"file": (f"v{revision}.txt", text.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 201, response.text
    payload: dict[str, object] = response.json()
    return payload


def transition(client: TestClient, version_id: str, target: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "target": target,
        "note": f"independent verification completed for transition {target}",
    }
    if target == "metadata_reviewed":
        payload["acknowledge_near_duplicate"] = True
        payload["acknowledge_extraction_quality"] = True
    response = client.post(
        f"/v1/document-versions/{version_id}/review",
        json=payload,
    )
    assert response.status_code == 200, response.text
    reviewed: dict[str, object] = response.json()
    return reviewed


def approve(client: TestClient, version_id: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for target in ("metadata_reviewed", "content_reviewed", "approved"):
        result = transition(client, version_id, target)
    return result


class StubSnapshotReader:
    """Читач знімка для подвійників репозиторію: одна тотожність, названа явно.

    Відколи релізна тотожність береться ЛИШЕ зі знімка, подвійник репозиторію без
    читача не вміє назвати реліз — і код правильно відмовляє. Це не незручність, а
    сенс зміни: місце, яке колись діставало другу, слабшу тотожність, тепер мусить
    сказати, яку саме тотожність воно вдає.
    """

    def __init__(self, release: str = "1" * 64, epoch: int = 1) -> None:
        self.release = release
        self.epoch = epoch
        self.captures = 0

    def capture(self, identity: object, corpus_ids: frozenset[str], as_of: date) -> CorpusReadToken:
        self.captures += 1
        corpora = frozenset(corpus_ids) & frozenset(getattr(identity, "corpora", corpus_ids))
        return CorpusReadToken(
            state_epoch=self.epoch,
            release_id=self.release,
            as_of=as_of,
            corpus_ids=corpora,
            authorization_scope_id="b" * 64,
        )

    def validate(
        self,
        identity: object,
        corpus_ids: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
    ) -> None:
        if token.state_epoch != self.epoch:
            raise CorpusConsistencyError("corpus state changed after read token capture")


def with_snapshot(repository: object, release: str = "1" * 64) -> object:
    """Причепити подвійникові репозиторію читача знімка й повернути його ж."""
    repository.corpus_snapshot_reader = StubSnapshotReader(release)  # type: ignore[attr-defined]
    return repository
