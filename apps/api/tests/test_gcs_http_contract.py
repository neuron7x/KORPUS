from __future__ import annotations

import httpx
import pytest

from korpus.infrastructure.gcs import GcsJsonClient, GcsPreconditionFailed


class Identity:
    def authorization_header(self) -> str:
        return "Bearer short-lived"

    def close(self) -> None:
        pass


def test_gcs_create_uses_generation_zero_precondition_and_workload_token() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.headers["Authorization"] == "Bearer short-lived"
        assert request.url.params["ifGenerationMatch"] == "0"
        assert request.url.params["uploadType"] == "media"
        return httpx.Response(200, json={"name": "objects/aa/item", "size": "3", "generation": "1"})

    gcs = GcsJsonClient(
        "korpus-objects",
        identity=Identity(),  # type: ignore[arg-type]
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert gcs.upload_create_only("objects/aa/item", b"abc")["generation"] == "1"
    assert len(captured) == 1


def test_gcs_precondition_failure_is_typed_not_retried_as_overwrite() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(412)

    gcs = GcsJsonClient(
        "korpus-objects",
        identity=Identity(),  # type: ignore[arg-type]
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(GcsPreconditionFailed):
        gcs.upload_create_only("objects/aa/item", b"abc")
