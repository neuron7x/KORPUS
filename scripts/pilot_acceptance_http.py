"""Bounded HTTP transport; credentials and response bodies never enter diagnostics."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from pilot_acceptance_contract import Fixture, ProbeFailure, identifier, object_payload, require

MAX_RESPONSE_BYTES = 1_048_576


def validate_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ProbeFailure("invalid base URL") from exc
    require(parsed.scheme in {"http", "https"} and bool(parsed.hostname), "invalid base URL")
    require(
        not (parsed.username or parsed.password or parsed.query or parsed.fragment),
        "base URL must not contain credentials, query or fragment",
    )
    require(port is None or port > 0, "invalid base URL port")
    if parsed.scheme == "http":
        try:
            loopback = ipaddress.ip_address(str(parsed.hostname)).is_loopback
        except ValueError:
            loopback = parsed.hostname == "localhost"
        require(loopback, "remote acceptance requires HTTPS; HTTP is allowed only on loopback")
    return value.rstrip("/")


def read_credential(reference: str) -> str:
    if reference.startswith("env:"):
        name = reference[4:]
        require(
            bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)),
            "invalid credential environment name",
        )
        value = os.environ.get(name, "")
    elif reference.startswith("file:"):
        try:
            with Path(reference[5:]).open(encoding="utf-8") as handle:
                value = handle.read(8193)
        except (OSError, UnicodeError) as exc:
            raise ProbeFailure("credential file cannot be read") from exc
    else:
        raise ProbeFailure("credentials must be env:NAME or file:PATH references")
    token = value.strip()
    require(1 <= len(token) <= 8192, "credential is absent or exceeds size limit")
    require(
        not any(char.isspace() or ord(char) < 32 for char in token), "invalid credential content"
    )
    return token


@dataclass(frozen=True)
class Response:
    status: int
    payload: Any

    def expect(self, status: int) -> Any:
        require(self.status == status, f"expected HTTP {status}, received HTTP {self.status}")
        return self.payload


class LiveHTTP:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = validate_base_url(base_url)
        require(0 < timeout <= 60, "HTTP timeout must be in (0, 60] seconds")
        self.timeout = timeout
        self.runner = asyncio.Runner()
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)

    def close(self) -> None:
        try:
            self.runner.run(self.client.aclose())
        finally:
            self.runner.close()

    def request(
        self,
        method: str,
        path: str,
        token: str | None,
        body: dict[str, object] | None = None,
        fixture: Fixture | None = None,
        timeout: float | None = None,
    ) -> Response:
        return self.runner.run(self.request_async(method, path, token, body, fixture, timeout))

    async def request_async(
        self,
        method: str,
        path: str,
        token: str | None,
        body: dict[str, object] | None,
        fixture: Fixture | None,
        timeout: float | None,
    ) -> Response:
        require(path.startswith("/v1/") and ".." not in path, "invalid probe endpoint")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        fields = None
        files = None
        if fixture is not None:
            fields = {
                "document_json": json.dumps(fixture.metadata()),
                "version_json": json.dumps(fixture.version()),
            }
            files = {"file": ("pilot-acceptance.txt", fixture.content, "text/plain")}
        duration = self.timeout if timeout is None else timeout
        require(0 < duration <= self.timeout, "invalid request deadline")
        deadline = time.monotonic() + duration
        try:
            async with asyncio.timeout(duration):
                async with self.client.stream(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=body,
                    data=fields,
                    files=files,
                    timeout=duration,
                ) as response:
                    content = await self.read_bounded(response)
                    result = Response(response.status_code, json.loads(content))
            require(time.monotonic() < deadline, "HTTP request exceeded its total deadline")
            return result
        except TimeoutError as exc:
            raise ProbeFailure("HTTP request exceeded its total deadline") from exc
        except (httpx.HTTPError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProbeFailure("HTTP transport or JSON decoding failed") from exc

    @staticmethod
    async def read_bounded(response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            require(size <= MAX_RESPONSE_BYTES, "HTTP response exceeds size limit")
            chunks.append(chunk)
        return b"".join(chunks)


def ingestion_result(
    http: LiveHTTP,
    token: str,
    fixture: Fixture,
    mode: str,
    deadline_seconds: float,
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if mode == "synchronous":
        return object_payload(
            http.request("POST", "/v1/documents/ingest", token, fixture=fixture).expect(201)
        )
    require(mode == "durable_async", "server reported unsupported ingestion mode")
    response = http.request("POST", "/v1/ingestion-jobs/documents", token, fixture=fixture)
    job = object_payload(response.expect(202))
    job_id = identifier(job.get("id"))
    if receipt is not None:
        receipt["job_id"] = job_id
    deadline = time.monotonic() + deadline_seconds
    while True:
        require(time.monotonic() < deadline, "ingestion job did not finish before deadline")
        require(job.get("id") == job_id, "ingestion polling changed job identity")
        state = job.get("state")
        if state == "succeeded":
            return object_payload(job.get("result"))
        require(
            state in {"queued", "running", "retryable"}, "ingestion job failed or has invalid state"
        )
        remaining = deadline - time.monotonic()
        require(remaining > 0, "ingestion job did not finish before deadline")
        time.sleep(min(0.2, remaining))
        remaining = deadline - time.monotonic()
        require(remaining > 0, "ingestion job did not finish before deadline")
        job = object_payload(
            http.request(
                "GET", f"/v1/ingestion-jobs/{job_id}", token, timeout=min(http.timeout, remaining)
            ).expect(200)
        )
