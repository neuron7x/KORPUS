"""Bounded evaluation transport to one operator-selected API origin."""

from __future__ import annotations

import asyncio
import math
from typing import Any
from uuid import UUID

import httpx
from evaluation_json import strict_json
from pilot_acceptance_contract import ProbeFailure
from pilot_acceptance_http import validate_base_url

MAX_RESPONSE_BYTES = 1024 * 1024


class InvalidEvidence(ValueError):
    """An observed response cannot establish the claimed evidence."""


class MeasurementUnavailable(RuntimeError):
    """Transport/dependency failure prevented a measurement."""


def canonical_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidEvidence("source identifier must be a UUID string")
    try:
        canonical = str(UUID(value))
    except ValueError as exc:
        raise InvalidEvidence("source identifier is not a UUID") from exc
    if canonical != value:
        raise InvalidEvidence("source identifier is not canonical")
    return canonical


class EvaluationHTTP:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if any(char.isspace() or ord(char) < 32 or char == "\\" for char in base_url):
            raise ValueError("invalid evaluation base URL")
        try:
            self.base_url = validate_base_url(base_url)
        except ProbeFailure as exc:
            raise ValueError("invalid evaluation base URL") from exc
        if isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("evaluation timeout must be finite and in (0,120] seconds")
        if len(token) > 8192 or any(char.isspace() or ord(char) < 32 for char in token):
            raise ValueError("invalid evaluation credential")
        self.token = token
        self.timeout = timeout
        self.runner = asyncio.Runner()
        self.client = httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, trust_env=False, transport=transport
        )

    def __enter__(self) -> EvaluationHTTP:
        return self

    def __exit__(self, *args: object) -> None:
        try:
            self.runner.run(self.client.aclose())
        finally:
            self.runner.close()

    def ask(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.runner.run(self._request("POST", "/v1/answers", body))

    def span(self, span_id: str, as_of: str) -> dict[str, Any]:
        from reference_eval_set import reference_date

        identifier = canonical_uuid(span_id)
        scope = reference_date(as_of)
        return self.runner.run(self._request("GET", f"/v1/spans/{identifier}?as_of={scope}"))

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with asyncio.timeout(self.timeout):
                async with self.client.stream(
                    method, f"{self.base_url}{path}", headers=headers, json=body
                ) as response:
                    self._status(response.status_code)
                    payload = strict_json(await self._read(response))
            if not isinstance(payload, dict):
                raise InvalidEvidence("evaluation response is not a JSON object")
            return payload
        except (TimeoutError, httpx.HTTPError, OSError) as exc:
            raise MeasurementUnavailable("transport_unavailable") from exc
        except (UnicodeError, ValueError) as exc:
            if isinstance(exc, InvalidEvidence):
                raise
            raise InvalidEvidence("evaluation response is invalid JSON") from exc

    @staticmethod
    def _status(status: int) -> None:
        if status == 429 or 500 <= status <= 599:
            raise MeasurementUnavailable(f"http_{status}")
        if status != 200:
            # Redirects are never followed, including on the answer POST. No bearer
            # is sent to a Location or source_uri supplied by the response.
            raise InvalidEvidence(f"source request refused with HTTP {status}")

    @staticmethod
    async def _read(response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise InvalidEvidence("evaluation response exceeds its size limit")
            chunks.append(chunk)
        return b"".join(chunks)
