"""Real HTTP/JWT acceptance, plus poisons that must make its verdict fail closed."""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

import httpx
import pytest
from korpus.config import Settings
from korpus.domain.models import Identity
from korpus.security.auth import issue_token

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from pilot_acceptance_contract import (  # noqa: E402
    ABSTENTION_TEXT,
    Credentials,
    Fixture,
    ProbeFailure,
    answer_citations,
    require_abstention,
    require_reader,
    sha256,
    verify_citation,
)
from pilot_acceptance_http import (  # noqa: E402
    LiveHTTP,
    Response,
    ingestion_result,
    read_credential,
    validate_base_url,
)
from run_pilot_acceptance import Options, PilotAcceptance  # noqa: E402

CORPUS = "pilot-smoke-http-test"


def token_credentials(secret: str, readers: int) -> Credentials:
    settings = Settings(_env_file=None, environment="local", auth_mode="jwt", jwt_secret=secret)

    def token(subject: str, role: str, corpus: str = CORPUS) -> str:
        identity = Identity(subject=subject, roles=frozenset({role}), corpora=frozenset({corpus}))
        return issue_token(identity, settings, lifetime_minutes=10)

    owner = token("fixture-owner", "curator")
    return Credentials(
        owner,
        tuple(token(f"reader-{index}", "user") for index in range(readers)),
        (owner, token("content-reviewer", "reviewer"), token("approver", "reviewer")),
        token("outsider", "user", "outsider-only"),
    )


def wait_until_serving(base_url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 20
    with httpx.Client(timeout=0.5, trust_env=False) as client:
        while time.monotonic() < deadline:
            assert process.poll() is None, "isolated uvicorn exited before startup"
            try:
                if client.get(f"{base_url}/health").status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.1)
    pytest.fail("isolated uvicorn did not become ready within 20 seconds")


@pytest.fixture(params=[("synchronous", 3), ("durable_async", 5)])
def live_pilot(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[tuple[str, Credentials, str]]:
    mode, reader_count = request.param
    secret = secrets.token_hex(32)
    credentials = token_credentials(secret, reader_count)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("KORPUS_")}
    environment.update(
        {
            "PYTHONPATH": str(ROOT / "apps/api/src"),
            "KORPUS_ENVIRONMENT": "local",
            "KORPUS_AUTH_MODE": "jwt",
            "KORPUS_JWT_SECRET": secret,
            "KORPUS_AUDIT_HMAC_KEY": secrets.token_hex(32),
            "KORPUS_DATABASE_URL": f"sqlite:///{tmp_path / 'pilot.db'}",
            "KORPUS_OBJECT_ROOT": str(tmp_path / "objects"),
            "KORPUS_QUARANTINE_OBJECT_ROOT": str(tmp_path / "quarantine"),
            "KORPUS_AUDIT_ANCHOR_PATH": str(tmp_path / "audit-anchor.json"),
            "KORPUS_INGESTION_MODE": mode,
            "KORPUS_REVIEW_SEPARATION_REQUIRED": "true",
        }
    )
    processes: list[subprocess.Popen[bytes]] = []
    with socket.socket() as listener, (tmp_path / "runtime.log").open("wb") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        try:
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "korpus.main:app",
                        "--fd",
                        str(listener.fileno()),
                        "--log-level",
                        "warning",
                        "--no-access-log",
                    ],
                    env=environment,
                    cwd=tmp_path,
                    pass_fds=(listener.fileno(),),
                    stdout=log,
                    stderr=log,
                )
            )
            wait_until_serving(base_url, processes[0])
            if mode == "durable_async":
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "korpus.cli",
                            "worker-loop",
                            "--idle-seconds",
                            "0.1",
                        ],
                        env=environment,
                        cwd=tmp_path,
                        stdout=log,
                        stderr=log,
                    )
                )
            yield base_url, credentials, mode
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def test_live_service_accepts_real_signed_readers_and_exact_sources(
    live_pilot: tuple[str, Credentials, str],
    tmp_path: Path,
) -> None:
    base_url, credentials, mode = live_pilot
    report_path = tmp_path / "acceptance.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/run_pilot_acceptance.py"),
        "--base-url",
        base_url,
        "--corpus-id",
        CORPUS,
        "--exercise-fixture",
        "--owner-credential",
        "env:PILOT_OWNER",
        "--content-credential",
        "env:PILOT_CONTENT",
        "--approver-credential",
        "env:PILOT_APPROVER",
        "--outsider-credential",
        "env:PILOT_OUTSIDER",
        "--out",
        str(report_path),
    ]
    environment = dict(os.environ)
    environment.update(
        PILOT_OWNER=credentials.owner,
        PILOT_CONTENT=credentials.reviewers[1],
        PILOT_APPROVER=credentials.reviewers[2],
        PILOT_OUTSIDER=credentials.outsider,
    )
    for index, token in enumerate(credentials.readers):
        environment[f"PILOT_READER_{index}"] = token
        command.extend(["--reader-credential", f"env:PILOT_READER_{index}"])
    completed = subprocess.run(
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert completed.returncode == 0, report
    assert report["status"] == "PASS", report
    assert report["transport"] == "live_http"
    assert report["ingestion_mode"] == mode
    assert report["reader_count"] == len(credentials.readers)
    assert report["admission_thresholds"] == {
        "min_retrieval_score": 0.18,
        "min_query_coverage": 0.5,
        "min_support_score": 0.18,
    }
    assert report["outsider_scope_verified"] is True
    assert len(report["fixture"]["span_ids"]) >= 1
    assert "reader_3_answer_and_sources" in report["completed_checks"]
    evidence = report_path.read_text() + completed.stdout + completed.stderr + repr(credentials)
    for token in (
        credentials.owner,
        *credentials.readers,
        *credentials.reviewers,
        credentials.outsider,
    ):
        assert token not in evidence
    duplicate = replace(credentials, readers=(credentials.readers[0],) * 3)
    refused = PilotAcceptance(Options(base_url, CORPUS, True), duplicate).run()
    assert refused["status"] == "FAIL"
    assert refused["failed_check"] == "identity_preflight"
    assert "fixture" not in refused


def test_fixture_mutations_require_explicit_scope_and_flag() -> None:
    credentials = Credentials("hidden", ("one", "two", "three"), ("hidden",) * 3)
    for options in (
        Options("http://127.0.0.1:1", CORPUS),
        Options("http://127.0.0.1:1", "public", True),
    ):
        report = PilotAcceptance(options, credentials).run()
        assert report["status"] == "FAIL"
        assert report["failed_check"] == "configuration"
        assert "base_url" not in report


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org",
        "https://user:secret@example.org",
        "https://example.org?token=secret",
        "file:///secret",
    ],
)
def test_credentials_cannot_be_sent_to_unsafe_origins(url: str) -> None:
    with pytest.raises(ProbeFailure):
        validate_base_url(url)


def test_credential_references_do_not_echo_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PILOT_SECRET", "private-token")
    assert read_credential("env:PILOT_SECRET") == "private-token"
    path = tmp_path / "token"
    path.write_text("private-token\n", encoding="utf-8")
    assert read_credential(f"file:{path}") == "private-token"
    with pytest.raises(ProbeFailure) as failure:
        read_credential("private-token")
    assert "private-token" not in str(failure.value)


@pytest.mark.parametrize(
    "answer",
    [
        {"status": "answered", "claims": [], "citations": []},
        {"status": "insufficient_evidence", "claims": [], "citations": [{"quote": "leak"}]},
        {"status": "insufficient_evidence", "claims": [{"text": "leak"}], "citations": []},
        {"status": "requires_human_review", "claims": [], "citations": []},
    ],
)
def test_non_abstentions_never_pass_blank_evidence_check(answer: dict[str, object]) -> None:
    with pytest.raises(ProbeFailure):
        require_abstention(answer)


@pytest.mark.parametrize("channel", ["text", "opening", "decision_reason", "limitations"])
def test_abstention_cannot_leak_through_rendered_channels(channel: str) -> None:
    fixture = Fixture(CORPUS)
    answer = {
        "status": "insufficient_evidence",
        "claims": [],
        "citations": [],
        "text": ABSTENTION_TEXT,
        "opening": "",
        "decision_reason": "retrieval_gate_failed",
        "limitations": ["Генерацію зупинено fail-closed."],
    }
    require_abstention(answer)
    leaked = fixture.content.decode("utf-8")
    answer[channel] = [leaked] if channel == "limitations" else leaked
    with pytest.raises(ProbeFailure):
        require_abstention(answer)


def test_answer_without_positive_fixture_fact_never_passes() -> None:
    with pytest.raises(ProbeFailure):
        answer_citations(
            {
                "status": "answered",
                "claims": [{"text": "other fact"}],
                "citations": [{"quote": "other fact"}],
            },
            Fixture(CORPUS),
        )
    with pytest.raises(ProbeFailure):
        require_reader({"answer:read", "document:list", "document:ingest"})


def test_claim_must_link_to_the_quotation_not_just_name_the_fixture() -> None:
    fixture = Fixture(CORPUS)
    span_id = str(uuid4())
    answer = {
        "status": "answered",
        "claims": [{"text": fixture.content.decode(), "evidence_span_ids": [span_id]}],
        "citations": [{"span_id": span_id, "quote": "unrelated heading"}],
    }
    with pytest.raises(ProbeFailure, match="not bound"):
        answer_citations(answer, fixture)


def test_redirect_does_not_forward_a_credential() -> None:
    seen: list[str] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://other.example/steal"}, json={})

    http = LiveHTTP("http://127.0.0.1:8000")
    http.runner.run(http.client.aclose())
    http.client = httpx.AsyncClient(transport=httpx.MockTransport(redirect), follow_redirects=False)
    try:
        with pytest.raises(ProbeFailure, match="received HTTP 307"):
            http.request("GET", "/v1/client/bootstrap", "never-echo-this-token").expect(200)
    finally:
        http.close()
    assert seen == ["http://127.0.0.1:8000/v1/client/bootstrap"]


@pytest.mark.parametrize("failure", ["timeout", "invalid_json", "oversize"])
def test_transport_failures_are_sanitized_and_fail_closed(failure: str) -> None:
    secret = "never-echo-this-token"

    def broken(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout(secret)
        content = secret.encode() if failure == "invalid_json" else b"x" * 1_048_577
        return httpx.Response(200, content=content)

    http = LiveHTTP("http://127.0.0.1:8000")
    http.runner.run(http.client.aclose())
    http.client = httpx.AsyncClient(transport=httpx.MockTransport(broken))
    try:
        with pytest.raises(ProbeFailure) as error:
            http.request("GET", "/v1/client/bootstrap", secret)
        assert secret not in str(error.value)
    finally:
        http.close()


@pytest.mark.parametrize("status", [401, 403, 404, 422, 500])
def test_http_failures_cannot_count_as_evidence_abstention(status: int) -> None:
    with pytest.raises(ProbeFailure):
        Response(status, {"status": "insufficient_evidence", "citations": [], "claims": []}).expect(
            200
        )


@pytest.mark.parametrize("state", ["dead_letter", "queued"])
def test_failed_or_unprocessed_durable_jobs_never_pass(state: str) -> None:
    job = {"id": str(uuid4()), "state": state}
    http = LiveHTTP("http://127.0.0.1:8000")
    http.runner.run(http.client.aclose())
    http.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(202, json=job))
    )
    try:
        with pytest.raises(ProbeFailure):
            ingestion_result(http, "private-token", Fixture(CORPUS), "durable_async", 0.001)
    finally:
        http.close()


class TrickleResponse(BaseHTTPRequestHandler):
    """Real TCP bytes arrive before each inactivity timeout, but too slowly overall."""

    def log_message(self, format: str, *args: object) -> None:
        return None

    def do_GET(self) -> None:
        content = b'{"ok": true}' + b" " * 200
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        try:
            for byte in content:
                self.wfile.write(bytes([byte]))
                self.wfile.flush()
                time.sleep(0.01)
        except (BrokenPipeError, ConnectionResetError):
            return None


def test_total_http_deadline_cancels_a_real_trickled_response() -> None:
    with ThreadingHTTPServer(("127.0.0.1", 0), TrickleResponse) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        http = LiveHTTP(f"http://127.0.0.1:{server.server_port}", timeout=0.12)
        started = time.monotonic()
        try:
            with pytest.raises(ProbeFailure, match="total deadline"):
                http.request("GET", "/v1/client/bootstrap", "private-token")
            assert time.monotonic() - started < 0.8
        finally:
            http.close()
            server.shutdown()
            thread.join(timeout=2)


def test_self_consistent_forged_span_cannot_claim_the_known_source_hash() -> None:
    fixture = Fixture(CORPUS)
    document_id, version_id, span_id = (str(uuid4()) for _ in range(3))
    forged = (
        fixture.content.decode().strip()
        + " Додаткова вигадана умова: плата за доступ становить 999 гривень."
    )
    citation = {
        "document_id": document_id,
        "version_id": version_id,
        "span_id": span_id,
        "source_hash": sha256(fixture.content),
        "span_hash": sha256(forged),
        "quote": forged,
        "quote_start": 0,
        "quote_end": len(forged),
        "quote_hash": sha256(forged),
    }
    span = {
        "id": span_id,
        "document_id": document_id,
        "version_id": version_id,
        "source_hash": sha256(fixture.content),
        "text": forged,
        "text_hash": sha256(forged),
    }
    answer = {
        "status": "answered",
        "text": forged,
        "opening": "",
        "claims": [{"text": forged, "evidence_span_ids": [span_id]}],
        "citations": [citation],
    }
    checked = answer_citations(answer, fixture)
    with pytest.raises(ProbeFailure, match="independently known upload"):
        verify_citation(checked[0], span, fixture, document_id, version_id)


@pytest.mark.parametrize("channel", ["text", "opening"])
def test_positive_answer_cannot_append_an_uncited_rendered_fact(channel: str) -> None:
    fixture = Fixture(CORPUS)
    span_id = str(uuid4())
    fact = fixture.content.decode().strip()
    answer = {
        "status": "answered",
        "text": fact,
        "opening": "",
        "claims": [{"text": fact, "evidence_span_ids": [span_id]}],
        "citations": [{"span_id": span_id, "quote": fact}],
    }
    answer_citations(answer, fixture)
    answer[channel] = fact + " Додаткова плата становить 999 гривень."
    with pytest.raises(ProbeFailure):
        answer_citations(answer, fixture)


@pytest.mark.parametrize(
    "poison",
    [
        "document_id",
        "version_id",
        "source_hash",
        "span_hash",
        "quote_hash",
        "quote_start",
        "quote_end",
        "span_text",
    ],
)
def test_broken_provenance_links_fail_closed(poison: str) -> None:
    fixture = Fixture(CORPUS)
    document_id, version_id, span_id = (str(uuid4()) for _ in range(3))
    text = fixture.content.decode("utf-8")
    citation = {
        "document_id": document_id,
        "version_id": version_id,
        "span_id": span_id,
        "source_hash": sha256(fixture.content),
        "span_hash": sha256(text),
        "quote": text,
        "quote_start": 0,
        "quote_end": len(text),
        "quote_hash": sha256(text),
    }
    span = {
        "id": span_id,
        "document_id": document_id,
        "version_id": version_id,
        "source_hash": sha256(fixture.content),
        "text": text,
        "text_hash": sha256(text),
    }
    verify_citation(citation, span, fixture, document_id, version_id)
    if poison == "span_text":
        span["text"] = "a substituted source"
    elif poison == "quote_start":
        citation[poison] = -1
    elif poison == "quote_end":
        citation[poison] = len(text) + 1
    else:
        citation[poison] = "substituted"
    with pytest.raises(ProbeFailure):
        verify_citation(citation, span, fixture, document_id, version_id)
