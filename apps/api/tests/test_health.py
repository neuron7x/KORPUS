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


def _refusal_detail(*, revision: str, expected: str, schema_mode: str) -> dict[str, object]:
    """Повний знімок зі шляху ВІДМОВИ — саме там оператор читає найуважніше.

    Успішна відповідь `/ready` віддає три слова й `schema_current` не несе взагалі
    (`readiness_projection.success_payload`). Поле з'являється рівно тоді, коли
    сервіс уже відмовляє з іншої причини й викладає знімок цілком.
    """
    snapshot = {
        "ready": False,  # відмова з іншої причини: розрив якоря на живому сервісі
        "schema_revision": revision,
        "expected_schema_revision": expected,
        "audit_head_sequence": 10433,
        "anchor_sequence": 10514,
        "anchor_matches_history": False,
    }
    repository = SimpleNamespace(readiness_snapshot=lambda **kwargs: snapshot)
    object_store = SimpleNamespace(healthcheck=lambda: True)
    settings = SimpleNamespace(
        resolved_metrics_token=None,  # ⇒ detail_permitted, знімок видно цілком
        audit_max_pending_events=10,
        audit_max_pending_age_seconds=10,
        schema_mode=schema_mode,
        semantic_retrieval_enabled=False,
    )
    with pytest.raises(HTTPException) as caught:
        ready(repository, object_store, settings, None, None, None)
    assert caught.value.status_code == 503
    detail = caught.value.detail
    assert isinstance(detail, dict)
    return detail


def test_schema_current_states_the_fact_and_schema_gated_states_the_policy() -> None:
    """Одне ім'я не сміє нести два предмети.

    ВИМІРЯНО 06.09.2026 на живому публічному сервісі. Відповідь `/ready` містила
    три рядки одночасно:

        schema_revision:          0022_approval_provenance_boundary
        expected_schema_revision: 0023_evidence_search_vector
        schema_current:           true

    Читач бере третій рядок за відповідь на питання, яке ставлять перші два. Поле
    відповідало правдиво, але на ІНШЕ питання — «чи гейтить тут схема». Обробник
    перезаписував факт зі знімка політикою розгортання.
    """
    detail = _refusal_detail(
        revision="0022_approval_provenance_boundary",
        expected="0023_evidence_search_vector",
        schema_mode="auto",
    )

    # ФАКТ: ревізії розходяться, і поле, чиє ім'я про це, мусить це казати.
    assert detail["schema_current"] is False
    # ПОЛІТИКА: тут не гейтить — і саме це пояснює, чому розбіжність прийнятна.
    assert detail["schema_gated"] is False
    # Обидва рядки-факти лишились на місці, читач бачить підставу.
    assert detail["schema_revision"] == "0022_approval_provenance_boundary"
    assert detail["expected_schema_revision"] == "0023_evidence_search_vector"


def test_matching_revisions_report_the_schema_as_current() -> None:
    """Дуал: без нього виправлення могло б просто вимкнути поле в нуль."""
    detail = _refusal_detail(
        revision="0023_evidence_search_vector",
        expected="0023_evidence_search_vector",
        schema_mode="migrations",
    )

    assert detail["schema_current"] is True
    assert detail["schema_gated"] is True


def test_a_gated_deployment_still_refuses_on_a_schema_mismatch() -> None:
    """Другий дуал: гейт, який мав боронити, мусить і далі боронити."""
    detail = _refusal_detail(
        revision="0022_approval_provenance_boundary",
        expected="0023_evidence_search_vector",
        schema_mode="migrations",
    )

    assert detail["schema_current"] is False
    assert detail["schema_gated"] is True
