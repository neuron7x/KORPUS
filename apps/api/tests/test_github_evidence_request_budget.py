"""Execute full four-producer admission through the bounded HTTPS transport itself."""

from __future__ import annotations

import ssl
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import github_evidence_import as importer  # noqa: E402
import github_evidence_transport as transport  # noqa: E402
from github_evidence_run import PACKAGE  # noqa: E402
from github_package_admission import package_producer  # noqa: E402

from .hosted_evidence_fixtures import EvidenceFixture, measured_fixture, with_security  # noqa: E402
from .test_github_evidence_live_base import COMPARE_PATH, PR, advanced_base_fixture  # noqa: E402


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> EvidenceFixture:
    fixture = with_security(
        advanced_base_fixture(measured_fixture(tmp_path_factory.mktemp("github-http-budget")))
    )
    producer = package_producer(fixture.checkout)
    fixture.add_artifact(
        producer, {name: b"neutral captured package member" for name in producer.required_members}
    )
    return fixture


class Response:
    def __init__(self, body: bytes, status: int = 200, location: str | None = None):
        self.body, self.status, self.location = body, status, location

    def getheader(self, name: str):
        assert name == "Location"
        return self.location

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


def _wire(monkeypatch, fixture: EvidenceFixture, storage_hops: int):
    requests: list[tuple[str, str]] = []
    storage: dict[str, Response] = {}
    connections: list = []
    storage_host = "productionresults.blob.core.windows.net"

    class Connection:
        def __init__(self, host: str, *, timeout: int, context: ssl.SSLContext):
            assert timeout == 30
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            self.host, self.closed = host, False
            connections.append(self)

        def request(self, method: str, path: str, *, headers: dict) -> None:
            assert method == "GET"
            if self.host == transport.API_HOST:
                assert headers["Authorization"] == "Bearer test-only-read-token"
                assert path.startswith(transport.API_PREFIX + "/")
            else:
                assert self.host == storage_host and "Authorization" not in headers
            self.path = path
            requests.append((self.host, path))

        def getresponse(self) -> Response:
            if self.host != transport.API_HOST:
                return storage[self.path]
            relative = self.path.removeprefix(transport.API_PREFIX)
            payload = fixture.api.responses[relative]
            if not relative.endswith(("/zip", "/logs")):
                return Response(payload)
            first = f"/captured/{len(requests)}/1"
            last = f"/captured/{len(requests)}/{storage_hops}"
            storage[first] = Response(b"", 302, f"https://{storage_host}{last}")
            storage[last] = Response(payload)
            return Response(b"", 302, f"https://{storage_host}{first}")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setenv("GITHUB_TOKEN", "test-only-read-token")
    monkeypatch.setattr(transport.http.client, "HTTPSConnection", Connection)
    api = transport.GitHubTransport()
    monkeypatch.setattr(importer, "capture_checkout", lambda root: fixture.checkout)
    monkeypatch.setattr(importer, "GitHubTransport", lambda: api)
    return api, requests, connections


def test_four_producers_with_live_base_ancestry_and_one_storage_hop_use_26_requests(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = measured.clone()
    api, requests, connections = _wire(monkeypatch, fixture, storage_hops=1)
    evidence, (package,) = importer.fetch_with_artifacts(fixture.checkout.root, PR, (PACKAGE,))
    assert len(evidence.artifacts) == 3 and package.producer_job_name == PACKAGE.job
    assert len(requests) == api._requests == 26 < transport.MAX_REQUESTS == 32
    metadata = [
        path.removeprefix(transport.API_PREFIX)
        for host, path in requests
        if host == transport.API_HOST and not path.endswith(("/zip", "/logs"))
    ]
    assert len(metadata) == 10 and metadata.count(COMPARE_PATH) == 1
    assert metadata.count("/pulls/113") == metadata.count("/git/ref/heads/main") == 2
    assert sum(host != transport.API_HOST for host, _path in requests) == 8
    assert all(connection.closed for connection in connections)


def test_excessive_combined_storage_hops_refuse_at_the_unchanged_request_limit(
    monkeypatch, measured: EvidenceFixture
) -> None:
    fixture = measured.clone()
    api, requests, connections = _wire(monkeypatch, fixture, storage_hops=2)
    with pytest.raises(ValueError, match="GitHub request budget exceeded"):
        importer.fetch_with_artifacts(fixture.checkout.root, PR, (PACKAGE,))
    assert len(requests) == transport.MAX_REQUESTS == 32
    assert api._requests == 33
    assert all(connection.closed for connection in connections)
