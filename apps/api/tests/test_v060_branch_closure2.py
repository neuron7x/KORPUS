from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from korpus.application.calibration import CalibrationProfile
from korpus.application.external_redteam import evaluate_external_redteam
from korpus.infrastructure.model_contract import (
    parse_composition,
    parse_query_variants,
    strip_code_fence,
)
from korpus.security import scanning
from pydantic import ValidationError


def test_model_contract_fail_closed_parse_matrix() -> None:
    assert strip_code_fence(" plain ") == "plain"
    assert strip_code_fence('```json\n["a"]\n```') == '["a"]\n'
    assert strip_code_fence("```") == ""

    assert parse_query_variants("no array") == []
    assert parse_query_variants("[broken]") == []
    assert parse_query_variants('{"x": 1}') == []
    assert parse_query_variants('["ok", 1, null]') == ["ok"]

    assert parse_composition("no object") == ("", [])
    assert parse_composition("{broken}") == ("", [])
    assert parse_composition("[1,2]") == ("", [])
    assert parse_composition('{"opening":"x","sentences":"not-list"}') == ("x", [])
    assert parse_composition('{"opening":"x","sentences":["a",1]}') == ("x", ["a"])


def _profile() -> dict[str, object]:
    return {
        "required_attack_families": ["ipi", "exfiltration"],
        "allowed_finding_severities": ["low", "high"],
        "allowed_finding_statuses": ["open", "closed"],
        "blocking_severities": ["high"],
        "blocking_finding_allowed_statuses": ["closed"],
    }


def test_external_redteam_structure_duplicate_family_and_blocking_matrix() -> None:
    profile = _profile()
    for report in (
        {"status": "FAIL", "test_cases": "bad", "findings": []},
        {"status": "FAIL", "test_cases": [{"id": "", "attack_family": "ipi"}], "findings": []},
        {"status": "FAIL", "test_cases": [{"id": "1", "attack_family": "unknown"}], "findings": []},
        {"status": "FAIL", "test_cases": [], "findings": "bad"},
        {
            "status": "FAIL",
            "test_cases": [
                {"id": "1", "attack_family": "ipi"},
                {"id": "2", "attack_family": "exfiltration"},
            ],
            "findings": [{"id": "", "severity": "low", "status": "closed"}],
        },
        {
            "status": "FAIL",
            "test_cases": [
                {"id": "1", "attack_family": "ipi"},
                {"id": "2", "attack_family": "exfiltration"},
            ],
            "findings": [{"id": "f1", "severity": "high", "status": "open"}],
        },
    ):
        verdict = evaluate_external_redteam(report, profile)
        assert not verdict["pass"]

    duplicate_findings = {
        "status": "FAIL",
        "test_cases": [
            {"id": "1", "attack_family": "ipi"},
            {"id": "2", "attack_family": "exfiltration"},
        ],
        "findings": [
            {"id": "same", "severity": "low", "status": "closed"},
            {"id": "same", "severity": "low", "status": "closed"},
        ],
    }
    assert not evaluate_external_redteam(duplicate_findings, profile)["pass"]

    good = {
        "status": "PASS",
        "test_cases": [
            {"id": "1", "attack_family": "ipi"},
            {"id": "2", "attack_family": "exfiltration"},
        ],
        "findings": [{"id": "f1", "severity": "high", "status": "closed"}],
    }
    assert evaluate_external_redteam(good, profile)["pass"]


def test_calibration_zero_sample_invalid_count_and_artifact_binding_edges(tmp_path: Path) -> None:
    # Construction validation reaches the explicit observed_errors guard before other evidence gates.
    def profile(**updates: object) -> CalibrationProfile:
        values: dict[str, object] = {
            "profile_id": "calibration-v060",
            "dataset_sha256": "a" * 64,
            "accepted_samples": 0,
            "observed_errors": 0,
            "confidence_delta": 0.05,
            "risk_limit": 0.05,
            "minimum_score": 0.4,
            "minimum_query_coverage": 0.5,
            "minimum_support_score": 0.35,
        }
        values.update(updates)
        return CalibrationProfile(**values)

    with pytest.raises(ValidationError, match="observed_errors"):
        profile(accepted_samples=1, observed_errors=2)

    profile = profile()
    assert profile.empirical_error == 1.0
    assert profile.upper_error_bound == 1.0

    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="artifact is missing"):
        profile.validate_artifact_bindings(
            dataset=missing,
            system_manifest=missing,
            evaluation_protocol=missing,
        )

    # Load digest mismatch is a content-addressing refusal, independent of profile validity.
    path = tmp_path / "profile.json"
    path.write_text(profile.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        CalibrationProfile.load(path, "0" * 64)
    assert (
        CalibrationProfile.load(path, hashlib.sha256(path.read_bytes()).hexdigest()).profile_id
        == profile.profile_id
    )


class _FakeConnection:
    def __init__(self, response: bytes, *, fail_send: bool = False) -> None:
        self.response = response
        self.fail_send = fail_send
        self.sent: list[bytes] = []
        self.timeout: float | None = None
        self._done = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def sendall(self, data: bytes) -> None:
        if self.fail_send:
            raise OSError("socket down")
        self.sent.append(data)

    def recv(self, maximum: int) -> bytes:
        if self._done:
            return b""
        self._done = True
        return self.response[:maximum]


def test_clamd_scan_protocol_ok_malware_unexpected_and_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"abcdef")

    with pytest.raises(ValueError, match="invalid clamd"):
        scanning.ClamdInstreamScanner("host", port=70000)

    connections: list[_FakeConnection] = []

    def install(response: bytes, *, fail_send: bool = False) -> _FakeConnection:
        connection = _FakeConnection(response, fail_send=fail_send)
        connections.append(connection)
        monkeypatch.setattr(scanning.socket, "create_connection", lambda *a, **k: connection)
        return connection

    ok = install(b"stream: OK\0")
    scanning.ClamdInstreamScanner("host", max_bytes=32, chunk_bytes=2).scan(sample)
    assert ok.timeout == 30.0
    assert ok.sent[0] == b"zINSTREAM\0" and ok.sent[-1] == b"\x00\x00\x00\x00"

    install(b"stream: Eicar-Test-Signature FOUND\0")
    with pytest.raises(scanning.MalwareDetectedError, match="Eicar-Test-Signature"):
        scanning.ClamdInstreamScanner("host").scan(sample)

    install(b"stream: protocol error\0")
    with pytest.raises(scanning.MalwareScannerUnavailable, match="unexpected"):
        scanning.ClamdInstreamScanner("host").scan(sample)

    install(b"", fail_send=True)
    with pytest.raises(scanning.MalwareScannerUnavailable, match="unavailable"):
        scanning.ClamdInstreamScanner("host").scan(sample)


def test_clamd_response_reader_handles_eof_newline_and_maximum() -> None:
    class Conn:
        def __init__(self, chunks: list[bytes]):
            self.chunks = iter(chunks)

        def recv(self, maximum: int) -> bytes:
            return next(self.chunks, b"")[:maximum]

    assert (
        scanning.ClamdInstreamScanner._read_response(Conn([b"stream: OK\n", b"later"]))
        == "stream: OK"
    )
    assert (
        scanning.ClamdInstreamScanner._read_response(Conn([b"abcd", b"efgh"]), maximum=4) == "abcd"
    )


def test_clamd_detects_file_growth_after_stat_before_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    from types import SimpleNamespace

    class GrowingPath:
        def stat(self):
            return SimpleNamespace(st_size=2)

        def open(self, mode: str):
            assert mode == "rb"
            return io.BytesIO(b"123456")

    connection = _FakeConnection(b"stream: OK\0")
    monkeypatch.setattr(scanning.socket, "create_connection", lambda *a, **k: connection)
    with pytest.raises(ValueError, match="size limit"):
        scanning.ClamdInstreamScanner("host", max_bytes=4, chunk_bytes=3).scan(GrowingPath())  # type: ignore[arg-type]
