"""Application-level request body ceilings for endpoints that bypass user auth."""
from __future__ import annotations

from fastapi import HTTPException, Request, status

MAX_WEBHOOK_BYTES = 64 * 1024


async def bounded_webhook_body(request: Request) -> bytes:
    """Read a webhook body without buffering past the application ceiling."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_WEBHOOK_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="payload too large",
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content length") from exc

    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > MAX_WEBHOOK_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="payload too large",
            )
        payload.extend(chunk)
    return bytes(payload)
