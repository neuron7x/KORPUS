from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from korpus.api.routes_health import ready
from korpus.application.embedding_coverage import assess_embedding_coverage


def test_health_and_readiness_are_operational_not_information_side_channels(client):
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready")
    assert ready.status_code == 200
    # `telemetry` is a bare status word: DISABLED, ACTIVE or REQUESTED_NOT_ACTIVE. The
    # third distinguishes "no tracing" from "tracing configured and going nowhere",
    # which an operator reading otlp_endpoint in the config cannot otherwise tell. The
    # endpoint itself stays out — this response is unauthenticated.
    assert ready.json() == {"status": "ready", "audit_head": 0, "telemetry": "DISABLED"}
    assert "http" not in ready.text.lower().replace("x-content-type-options", "")
    assert "corpus_release" not in ready.text
    assert ready.headers["X-Content-Type-Options"] == "nosniff"
    assert ready.headers["Cache-Control"] == "no-store"
    assert ready.headers["X-Request-ID"]


def test_required_semantic_index_blocks_readiness_when_coverage_is_incomplete() -> None:
    snapshot = {
        "ready": True,
        "schema_revision": "head",
        "expected_schema_revision": "head",
    }
    repository = SimpleNamespace(readiness_snapshot=lambda **kwargs: snapshot)
    object_store = SimpleNamespace(healthcheck=lambda: True)
    coverage = assess_embedding_coverage(
        active_model_id="model-v2",
        active_dimensions=8,
        spans_total=10,
        spans_embedded_active=9,
        spans_embedded_other_model=0,
        spans_stale_text=0,
    )
    semantic = SimpleNamespace(
        corpus_governance=SimpleNamespace(corpora={"public": object()}),
        coverage=lambda identity, corpora: coverage,
    )
    settings = SimpleNamespace(
        resolved_metrics_token="operator-token",
        audit_max_pending_events=10,
        audit_max_pending_age_seconds=10,
        schema_mode="migrations",
        semantic_retrieval_enabled=True,
    )

    with pytest.raises(HTTPException) as caught:
        ready(repository, object_store, settings, semantic, None, None)

    assert caught.value.status_code == 503
    assert caught.value.detail == {"ready": False, "reason": "semantic_index"}
