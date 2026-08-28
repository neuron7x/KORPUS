"""Configuration admission for the embedding provider, and the batch it refuses to send.

The provider talks to an external model over HTTP. Its constructor is where a deployment
mistake is still cheap: a plaintext endpoint, a model id that is not one, a batch ceiling
above what the service accepts. Measured on 2026-08-28 the module sat at 85% branch
coverage with the refusing side of each check untaken.

The endpoint rule is the one with teeth. Embedding requests carry corpus text, so a
plaintext `http://` endpoint to anywhere but loopback ships controlled material in the
clear — the check is a confidentiality boundary, not a style preference.
"""

from __future__ import annotations

import pytest
from korpus.infrastructure.embedding_provider import HttpEmbeddingProvider


class _Client:
    def get(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("no request should be made in these tests")

    def post(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("no request should be made in these tests")

    def close(self) -> None:
        pass


def _provider(**changes: object) -> HttpEmbeddingProvider:
    values: dict[str, object] = {
        "endpoint": "https://embeddings.example/v1/embeddings",
        "model_id": "qwen3-embedding-0.6b",
        "dimensions": 1024,
        "client": _Client(),
    }
    values.update(changes)
    return HttpEmbeddingProvider(**values)  # type: ignore[arg-type]


def test_a_well_formed_configuration_is_accepted() -> None:
    """The dual: refusing everything would satisfy each assertion below."""
    assert _provider().model_id == "qwen3-embedding-0.6b"
    assert _provider(endpoint="http://127.0.0.1:8080/embed").endpoint.startswith("http://127.")


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://embeddings.example/v1",
        "ftp://embeddings.example/v1",
        "embeddings.example/v1",
        "",
        "http://10.0.0.5/embed",
    ],
)
def test_a_plaintext_or_malformed_endpoint_is_refused(endpoint: str) -> None:
    """Corpus text leaves the process in the request body; the transport has to hold."""
    with pytest.raises(ValueError, match="HTTPS or loopback"):
        _provider(endpoint=endpoint)


@pytest.mark.parametrize("model_id", ["", "model id with spaces", "model\nid", "x" * 300, "модель"])
def test_a_model_id_that_is_not_one_is_refused(model_id: str) -> None:
    """The id is interpolated into the request; its shape is fixed before it is sent.

    Slashes and dots are admitted on purpose — an id like `org/model-v1.2` is ordinary —
    so the pattern bounds the character set and the length rather than the path shape.
    """
    with pytest.raises(ValueError, match="invalid embedding model configuration"):
        _provider(model_id=model_id)


@pytest.mark.parametrize("batch", [0, -1, 65, 1000])
def test_a_batch_ceiling_outside_the_supported_range_is_refused(batch: int) -> None:
    """Zero can never send anything; above 64 the service rejects the request itself."""
    with pytest.raises(ValueError):
        _provider(max_batch_size=batch)


@pytest.mark.parametrize("texts", [[], ["ok"] * 33])
def test_a_batch_of_the_wrong_cardinality_is_refused_before_the_request(
    texts: list[str],
) -> None:
    """Empty costs a round trip for nothing; oversized is refused by the service anyway."""
    with pytest.raises(ValueError, match="batch cardinality is invalid"):
        _provider().embed_many(texts)


@pytest.mark.parametrize("text", ["", "x" * 12_001])
def test_an_input_outside_the_length_bounds_is_refused_before_the_request(text: str) -> None:
    """An empty string has no embedding; an oversized one is truncated silently upstream."""
    with pytest.raises(ValueError, match="input length is invalid"):
        _provider().embed_many(["valid", text])


def test_a_healthcheck_that_cannot_reach_the_service_is_false_rather_than_raising() -> None:
    """Fail closed: an unanswerable question is not a positive answer."""
    import httpx

    class Unreachable(_Client):
        def get(self, *args: object, **kwargs: object) -> object:
            raise httpx.ConnectError("no route to host")

    assert _provider(client=Unreachable()).healthcheck() is False


def test_a_healthcheck_reads_the_status_code_rather_than_the_body() -> None:
    """A 4xx means the probe was wrong; a 5xx means the service is. Only 5xx is unhealthy."""

    class Responding(_Client):
        def __init__(self, status: int) -> None:
            self.status = status

        def get(self, *args: object, **kwargs: object) -> object:
            return type("R", (), {"status_code": self.status})()

    assert _provider(client=Responding(200)).healthcheck() is True
    assert _provider(client=Responding(404)).healthcheck() is True
    assert _provider(client=Responding(500)).healthcheck() is False
    assert _provider(client=Responding(503)).healthcheck() is False
