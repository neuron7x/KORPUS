from __future__ import annotations

from korpus.api.overload_http import overload_http_exception
from korpus.application.overload import OverloadedError, OverloadReason


def test_subject_share_exhaustion_is_http_429_with_retry_after() -> None:
    response = overload_http_exception(OverloadedError(OverloadReason.SUBJECT_SHARE))
    assert response.status_code == 429
    assert response.detail == {"reason": "subject_share_exhausted", "retry_after_seconds": 1}
    assert response.headers == {"Retry-After": "1"}


def test_global_capacity_exhaustion_remains_http_503() -> None:
    response = overload_http_exception(OverloadedError(OverloadReason.GLOBAL_CAPACITY))
    assert response.status_code == 503
    assert response.detail["reason"] == "global_capacity_exhausted"
    assert response.headers == {"Retry-After": "1"}
