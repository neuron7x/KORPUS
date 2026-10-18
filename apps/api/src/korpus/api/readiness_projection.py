from __future__ import annotations

from collections.abc import Mapping

from korpus.application.numeric_contracts import require_count


def success_payload(
    *, detail_permitted: bool, snapshot: Mapping[str, object], telemetry: str
) -> dict[str, object]:
    if not detail_permitted:
        return {"status": "ready"}
    return {
        "status": "ready",
        "audit_head": require_count(snapshot.get("audit_head_sequence"), label="audit head"),
        "telemetry": telemetry,
    }


def schema_fields(snapshot: Mapping[str, object], schema_mode: str) -> dict[str, object]:
    """Факт про схему і політику щодо неї — двома іменами, не одним.

    Підстава й вимір: `test_health.test_schema_current_states_the_fact_and_schema_gated_states_the_policy`.
    """
    return {
        "schema_current": snapshot["schema_revision"] == snapshot["expected_schema_revision"],
        "schema_gated": schema_mode == "migrations",
    }
