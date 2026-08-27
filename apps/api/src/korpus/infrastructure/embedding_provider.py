from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from korpus.application.resilience import CircuitBreaker
from korpus.infrastructure.embedding_envelope import embedding_vectors
from korpus.infrastructure.embedding_validation import normalize_vector
from korpus.infrastructure.resource_contracts import count, embedding_limits
from korpus.security.url_policy import is_https_or_loopback_url

MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]{1,200}$")


class EmbeddingHttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def content(self) -> bytes: ...

    def raise_for_status(self) -> object: ...
    def json(self) -> Any: ...


class EmbeddingHttpClient(Protocol):
    def post(self, url: str, *, json: Any) -> EmbeddingHttpResponse: ...
    def get(self, url: str, *, headers: Mapping[str, str]) -> EmbeddingHttpResponse: ...


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...
    def embed_many(self, texts: list[str]) -> list[list[float]]: ...
    def healthcheck(self) -> bool: ...
    def close(self) -> None: ...


@dataclass
class HttpEmbeddingProvider:
    """Bounded, non-authoritative embedding integration with circuit breaking."""

    endpoint: str
    model_id: str
    dimensions: int
    token: str | None = None
    timeout_seconds: float = 5.0
    max_attempts: int = 3
    max_response_bytes: int = 2 * 1024 * 1024
    max_batch_size: int = 32
    client: EmbeddingHttpClient | None = None

    def __post_init__(self) -> None:
        if not is_https_or_loopback_url(self.endpoint):
            raise ValueError("embedding endpoint must use HTTPS or loopback HTTP")
        if not MODEL_PATTERN.fullmatch(self.model_id):
            raise ValueError("invalid embedding model configuration")
        try:
            self.dimensions, self.max_attempts, self.max_response_bytes, self.timeout_seconds = (
                embedding_limits(
                    self.dimensions,
                    self.max_attempts,
                    self.max_response_bytes,
                    self.timeout_seconds,
                )
            )
        except ValueError as exc:
            raise ValueError(f"invalid embedding resilience configuration: {exc}") from exc
        self.max_batch_size = count(self.max_batch_size, 1, "max_batch_size")
        if self.max_batch_size > 64:
            raise ValueError("max_batch_size must not exceed 64")
        if self.client is None:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            self.client = httpx.Client(
                timeout=httpx.Timeout(self.timeout_seconds),
                headers=headers,
                limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
                transport=httpx.HTTPTransport(retries=self.max_attempts - 1),
            )
        self._client: EmbeddingHttpClient = self.client
        self._circuit = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=15.0)

    def _response_vectors(self, text: str | list[str]) -> list[list[float]]:
        response = self._client.post(self.endpoint, json={"model": self.model_id, "input": text})
        response.raise_for_status()
        if len(response.content) > self.max_response_bytes:
            raise RuntimeError("embedding response exceeds configured limit")
        candidates = embedding_vectors(response.json())
        expected = 1 if isinstance(text, str) else len(text)
        if candidates is None or len(candidates) != expected:
            raise RuntimeError("embedding service returned invalid batch cardinality")
        return [normalize_vector(candidate, self.dimensions) for candidate in candidates]

    def embed(self, text: str) -> list[float]:
        if not text or len(text) > 12_000:
            raise ValueError("embedding input length is invalid")
        return self._circuit.call(lambda: self._response_vectors(text)[0])

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts or len(texts) > self.max_batch_size:
            raise ValueError("embedding batch cardinality is invalid")
        if any(not text or len(text) > 12_000 for text in texts):
            raise ValueError("embedding input length is invalid")
        return self._circuit.call(lambda: self._response_vectors(texts))

    def healthcheck(self) -> bool:
        try:
            response = self._client.get(self.endpoint, headers={"Accept": "application/json"})
            return response.status_code < 500
        except (httpx.HTTPError, OSError, RuntimeError, ValueError):
            return False

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()
