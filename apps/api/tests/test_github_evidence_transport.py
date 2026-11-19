"""The network boundary is fixed HTTPS, read-only, bounded and credential-isolated."""

from __future__ import annotations

import ssl
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import github_evidence_source as source  # noqa: E402
import github_evidence_transport as transport  # noqa: E402


class Response:
    def __init__(self, body: bytes, status: int = 200, location: str | None = None):
        self.body, self.status, self.location = body, status, location

    def getheader(self, name: str):
        assert name == "Location"
        return self.location

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


@pytest.fixture
def wire(monkeypatch):
    responses: list[Response] = []
    requests: list[dict] = []

    class Connection:
        def __init__(self, host: str, *, timeout: int, context: ssl.SSLContext):
            assert timeout == transport.TIMEOUT_SECONDS
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            assert context.keylog_filename is None
            self.host = host

        def request(self, method: str, path: str, *, headers: dict) -> None:
            requests.append({"method": method, "host": self.host, "path": path, "headers": headers})

        def getresponse(self) -> Response:
            return responses.pop(0)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(transport.http.client, "HTTPSConnection", Connection)
    monkeypatch.setenv("GITHUB_TOKEN", "test-only-read-token")
    return responses, requests


def test_api_uses_fixed_repository_https_get_and_canonical_headers(wire) -> None:
    responses, requests = wire
    responses.append(Response(b'{"id":123}'))
    assert transport.GitHubTransport().json("/actions/runs/123") == {"id": 123}
    assert requests == [
        {
            "method": "GET",
            "host": "api.github.com",
            "path": "/repos/neuron7x/KORPUS/actions/runs/123",
            "headers": {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Authorization": "Bearer test-only-read-token",
                "User-Agent": "KORPUS-hosted-evidence/1",
            },
        }
    ]


def test_storage_redirect_never_receives_github_token(wire) -> None:
    responses, requests = wire
    responses.extend(
        [
            Response(b"", 302, "https://productionresults.blob.core.windows.net/artifact?sig=test"),
            Response(b"immutable zip bytes"),
        ]
    )
    assert (
        transport.GitHubTransport().download("/actions/artifacts/123/zip", 100)
        == b"immutable zip bytes"
    )
    assert requests[0]["headers"]["Authorization"] == "Bearer test-only-read-token"
    assert "Authorization" not in requests[1]["headers"]


def test_pr_metadata_uses_the_existing_contents_read_token(wire) -> None:
    responses, requests = wire
    responses.append(Response(b'{"number":113}'))
    assert transport.GitHubTransport().json("/pulls/113") == {"number": 113}
    assert requests[0]["headers"].get("Authorization") == "Bearer test-only-read-token"


@pytest.mark.parametrize("status", [401, 403, 429])
def test_refused_pr_metadata_records_endpoint_without_anonymous_retry(wire, status: int) -> None:
    responses, requests = wire
    responses.append(Response(b'{"message":"request refused"}', status))
    with pytest.raises(ValueError, match=f"HTTP {status}.*pulls/113") as failure:
        transport.GitHubTransport().json("/pulls/113")
    assert len(requests) == 1
    assert requests[0]["headers"].get("Authorization") == "Bearer test-only-read-token"
    assert "test-only-read-token" not in str(failure.value)


def test_ambient_tls_keylog_variable_cannot_export_credentials(wire, monkeypatch, tmp_path) -> None:
    responses, _requests = wire
    path = tmp_path / "tls-keylog.txt"
    monkeypatch.setenv("SSLKEYLOGFILE", str(path))
    responses.append(Response(b"{}"))
    transport.GitHubTransport().json("/actions/runs/123")
    assert not path.exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://productionresults.blob.core.windows.net/x",
        "https://attacker.example/x",
        "https://productionresults.blob.core.windows.net.attacker.example/x",
        "https://user:secret@productionresults.blob.core.windows.net/x",
        "https://productionresults.blob.core.windows.net:444/x",
        "https://productionresults.blob.core.windows.net/x#fragment",
        "file:///tmp/claimed-artifact.zip",
    ],
)
def test_noncanonical_download_redirect_is_rejected_before_contact(wire, url: str) -> None:
    responses, requests = wire
    responses.append(Response(b"", 302, url))
    with pytest.raises(ValueError, match="HTTPS storage allowlist"):
        transport.GitHubTransport().download("/actions/artifacts/123/zip", 100)
    assert len(requests) == 1


@pytest.mark.parametrize("body", [b'{"id":1,"id":2}', b'{"value":NaN}', b'{"value":1e999}', b"[]"])
def test_authenticated_json_still_requires_one_unambiguous_object(wire, body: bytes) -> None:
    responses, _requests = wire
    responses.append(Response(body))
    with pytest.raises(ValueError):
        transport.GitHubTransport().json("/actions/runs/123")


def test_download_and_json_responses_have_finite_byte_limits(wire, monkeypatch) -> None:
    responses, _requests = wire
    responses.append(Response(b"x" * 101))
    with pytest.raises(ValueError, match="byte budget exceeded"):
        transport.GitHubTransport().download("/actions/artifacts/123/zip", 100)
    monkeypatch.setattr(transport, "MAX_METADATA_BYTES", 10)
    responses.append(Response(b'{"oversized":"metadata"}'))
    with pytest.raises(ValueError, match="byte budget exceeded"):
        transport.GitHubTransport().json("/actions/runs/123")


def test_network_refusal_never_uses_saved_metadata_or_artifact_fallback(wire) -> None:
    responses, requests = wire
    responses.append(Response(b'{"status":"PASS"}', 403))
    with pytest.raises(ValueError, match="HTTP 403"):
        transport.GitHubTransport().json("/actions/runs/123")
    assert len(requests) == 1


def test_request_and_redirect_counts_are_bounded(wire, monkeypatch) -> None:
    responses, requests = wire
    monkeypatch.setattr(transport, "MAX_REQUESTS", 2)
    responses.extend([Response(b"{}"), Response(b"{}")])
    api = transport.GitHubTransport()
    api.json("/actions/runs/1")
    api.json("/actions/runs/2")
    with pytest.raises(ValueError, match="request budget"):
        api.json("/actions/runs/3")
    assert len(requests) == 2


def test_missing_trusted_git_is_a_refusal_not_an_identity_fallback(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(source, "_command", lambda root, *args: None)
    with pytest.raises(ValueError, match="trusted Git checkout identity is unavailable"):
        source.capture_checkout(tmp_path)
