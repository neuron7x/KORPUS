from __future__ import annotations

from typing import Any

import pytest
from korpus.application.query_plan import PlannerUnavailable
from korpus.application.resilience import CircuitBreaker
from korpus.infrastructure.model_transport import MAX_MODEL_RESPONSE_BYTES, guarded_json_post


class _Response:
    def __init__(self, content: bytes, *, declared: int | None = None) -> None:
        self.content = content
        self.headers = {} if declared is None else {"content-length": str(declared)}
        self.json_called = False

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, bool]:
        self.json_called = True
        return {"admitted": True}


def _post(response: _Response) -> Any:
    return guarded_json_post(
        CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=1),
        lambda *_args, **_kwargs: response,
        url="https://provider.invalid/v1/model",
        headers={},
        payload={},
        timeout=1,
    )


def test_model_transport_admits_response_at_exact_byte_ceiling() -> None:
    assert _post(_Response(b"x" * MAX_MODEL_RESPONSE_BYTES)) == {"admitted": True}


@pytest.mark.parametrize(
    "response",
    [
        _Response(b"x" * (MAX_MODEL_RESPONSE_BYTES + 1)),
        _Response(b"{}", declared=MAX_MODEL_RESPONSE_BYTES + 1),
    ],
)
def test_model_transport_refuses_oversized_body_before_json_decode(response: _Response) -> None:
    with pytest.raises(PlannerUnavailable, match="model response exceeds byte ceiling"):
        _post(response)
    assert response.json_called is False
