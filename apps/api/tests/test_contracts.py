from __future__ import annotations


def test_openapi_contract_exposes_evidence_and_decision_provenance(client):
    schema = client.get("/openapi.json").json()
    query = schema["components"]["schemas"]["QueryRequest"]
    assert not {"clearance", "roles", "user_tier"}.intersection(query.get("properties", {}))

    answer_properties = schema["components"]["schemas"]["Answer"]["properties"]
    assert {"decision_reason", "calibration_id", "corpus_release", "evidence_coverage"} <= set(answer_properties)

    citation_properties = schema["components"]["schemas"]["Citation"]["properties"]
    assert {"quote_start", "quote_end", "quote_hash", "source_hash", "span_id"} <= set(citation_properties)


def test_contract_rejects_duplicate_or_invalid_corpus_ids(client):
    duplicate = client.post(
        "/v1/answers",
        json={"text": "valid query", "corpus_ids": ["public", "public"]},
    )
    invalid = client.post(
        "/v1/answers",
        json={"text": "valid query", "corpus_ids": ["../escape"]},
    )
    assert duplicate.status_code == 422
    assert invalid.status_code == 422
