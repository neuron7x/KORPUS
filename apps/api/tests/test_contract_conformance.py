"""The published contract, enforced against live responses.

A schema nothing validates is documentation. This module makes drift between
`packages/contracts/answer.schema.json` and the API a failing test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from conftest import CORPUS, make_span
from jsonschema import Draft202012Validator

from korpus.api import routes
from korpus.domain.access import Principal
from korpus.domain.models import AccessTier

CONTRACTS = Path(__file__).resolve().parents[3] / "packages/contracts"
SCHEMA_PATH = CONTRACTS / "answer.schema.json"


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def assert_conforms(validator: Draft202012Validator, body: dict[str, Any]) -> None:
    errors = sorted(validator.iter_errors(body), key=lambda error: error.json_path)
    assert not errors, "; ".join(f"{e.json_path}: {e.message}" for e in errors)


def test_schema_file_is_a_valid_2020_12_schema(validator: Draft202012Validator) -> None:
    assert validator.schema["$id"].endswith("answer.schema.json")


def test_answered_response_conforms(client, validator) -> None:  # type: ignore[no-untyped-def]
    routes._retriever.add(make_span(text="порядок евакуації поранених"))
    body = client.post("/v1/answers", json={"text": "порядок евакуації"}).json()
    assert body["status"] == "answered"
    assert_conforms(validator, body)


def test_abstention_response_conforms(client, validator) -> None:  # type: ignore[no-untyped-def]
    body = client.post("/v1/answers", json={"text": "запит без джерел у корпусі"}).json()
    assert body["status"] == "insufficient_evidence"
    assert_conforms(validator, body)


def test_access_denied_response_conforms(client, validator) -> None:  # type: ignore[no-untyped-def]
    body = client.post(
        "/v1/answers",
        json={"text": "покажи матеріал", "corpus_ids": [str(uuid4())]},
    ).json()
    assert body["status"] == "access_denied"
    assert_conforms(validator, body)


def test_review_response_conforms(client, validator) -> None:  # type: ignore[no-untyped-def]
    """A response held for review must still be a well-formed answer object."""

    class UncitedGenerator:
        async def compose(self, query: object, evidence: object) -> list:  # type: ignore[type-arg]
            del query, evidence
            from korpus.domain.models import Claim

            return [Claim(text="Твердження без джерела.")]

    routes._retriever.add(make_span(text="порядок евакуації поранених"))
    original = routes.EvidenceBoundStubGenerator
    routes.EvidenceBoundStubGenerator = UncitedGenerator  # type: ignore[misc,assignment]
    try:
        body = client.post("/v1/answers", json={"text": "порядок евакуації"}).json()
    finally:
        routes.EvidenceBoundStubGenerator = original  # type: ignore[misc]
    assert body["status"] == "requires_human_review"
    # A hold hands nothing over: the reviewer reads the evidence from the audit trail.
    assert body["citations"] == []
    assert body["claims"] == []
    assert_conforms(validator, body)


def test_denial_carries_no_evidence(client, validator) -> None:  # type: ignore[no-untyped-def]
    """The property the schema encodes, asserted directly: a refusal leaks nothing."""
    routes._retriever.add(make_span(text="таємний порядок", tier=AccessTier.RESTRICTED))
    body = client.post(
        "/v1/answers",
        json={"text": "таємний порядок", "corpus_ids": [str(uuid4())]},
    ).json()
    assert body["citations"] == []
    assert body["claims"] == []
    assert_conforms(validator, body)


def test_restricted_material_is_absent_from_a_public_answer(client) -> None:  # type: ignore[no-untyped-def]
    secret = make_span(text="порядок евакуації таємний", tier=AccessTier.RESTRICTED)
    routes._retriever.add(secret)
    body = client.post("/v1/answers", json={"text": "порядок евакуації"}).json()
    serialized = json.dumps(body, ensure_ascii=False)
    assert str(secret.chunk_id) not in serialized
    assert secret.citation.quote not in serialized


def test_authorized_principal_reaches_restricted_material(client) -> None:  # type: ignore[no-untyped-def]
    secret = make_span(text="порядок евакуації таємний", tier=AccessTier.RESTRICTED)
    routes._retriever.add(secret)
    routes._resolver._table["cmd-token"] = Principal(  # noqa: SLF001 - test wiring
        subject_id="commander",
        tier=AccessTier.RESTRICTED,
        authorized_corpora=frozenset({CORPUS}),
    )
    body = client.post(
        "/v1/answers",
        json={"text": "порядок евакуації таємний"},
        headers={"Authorization": "Bearer cmd-token"},
    ).json()
    assert body["status"] == "answered"
    assert any(c["chunk_id"] == str(secret.chunk_id) for c in body["citations"])
