from __future__ import annotations

from fastapi import HTTPException, status

from korpus.application.overload import OverloadedError, OverloadReason


def overload_http_exception(
    error: OverloadedError, *, retry_after_seconds: int = 1
) -> HTTPException:
    """Map typed admission refusal to stable HTTP semantics.

    A subject that exhausted only its own share is being throttled (429). Global
    capacity exhaustion means the service itself has no slot available (503).
    """
    status_code = (
        status.HTTP_429_TOO_MANY_REQUESTS
        if error.reason is OverloadReason.SUBJECT_SHARE
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    retry_after = str(retry_after_seconds)
    return HTTPException(
        status_code=status_code,
        detail={"reason": error.reason.value, "retry_after_seconds": retry_after_seconds},
        headers={"Retry-After": retry_after},
    )
