"""Neutral in-memory archives and HTTP doubles; no release binary is executed here."""

from __future__ import annotations

import gzip
import hashlib
import io
import signal
import ssl
import tarfile

import pytest

from scripts import scanner_engine_artifact as artifact
from scripts import scanner_engine_download as download


def _elf() -> bytes:
    raw = bytearray(64)
    raw[:7] = b"\x7fELF\x02\x01\x01"
    raw[16:18], raw[18:20] = b"\x02\0", b"\x3e\0"
    return bytes(raw)


def _archive(entries: list[tuple[str, bytes, bytes]]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, raw, kind in entries:
            member = tarfile.TarInfo(name)
            member.type, member.size = kind, len(raw)
            member.linkname = "/outside" if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE} else ""
            archive.addfile(member, io.BytesIO(raw))
    return gzip.compress(stream.getvalue())


def _pin(monkeypatch: pytest.MonkeyPatch, raw: bytes) -> None:
    for module in (artifact, download):
        monkeypatch.setattr(module, "ARCHIVE_SIZE", len(raw))
        monkeypatch.setattr(module, "ARCHIVE_SHA256", hashlib.sha256(raw).hexdigest())


class Response:
    def __init__(self, status: int, headers: list[tuple[str, str]], body: bytes = b"") -> None:
        self.status, self.headers, self.body = status, headers, body

    def getheaders(self) -> list[tuple[str, str]]:
        return self.headers

    def read1(self, size: int) -> bytes:
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


def _transport(monkeypatch: pytest.MonkeyPatch, responses: list[Response]) -> list[dict]:
    calls = []

    class Connection:
        def __init__(self, host: str, timeout: int, context: ssl.SSLContext) -> None:
            assert timeout == 10 and context.verify_mode == ssl.CERT_REQUIRED
            assert context.check_hostname
            self.record = {"host": host, "closed": False}
            self.response = responses.pop(0)
            calls.append(self.record)

        def request(self, method: str, target: str, headers: dict[str, str]) -> None:
            self.record.update(method=method, target=target, headers=headers)

        def getresponse(self) -> Response:
            return self.response

        def close(self) -> None:
            self.record["closed"] = True

    monkeypatch.setattr(download.http.client, "HTTPSConnection", Connection)
    return calls


def test_exact_public_download_follows_only_bounded_explicit_redirects(monkeypatch) -> None:
    raw = b"neutral archive identity"
    _pin(monkeypatch, raw)
    monkeypatch.setenv("GITHUB_TOKEN", "unit-token-must-never-be-used")
    calls = _transport(
        monkeypatch,
        [
            Response(
                302, [("Location", "https://release-assets.githubusercontent.com/a?opaque=x")]
            ),
            Response(307, [("Location", "https://objects.githubusercontent.com/final")]),
            Response(
                200, [("Content-Length", str(len(raw))), ("Content-Encoding", "identity")], raw
            ),
        ],
    )
    observed, hosts = download.download_archive()
    assert observed == raw and hosts == [item["host"] for item in calls]
    assert len(calls) == 3 and all(item["closed"] for item in calls)
    assert calls[1]["target"] == "/a?opaque=x"
    assert all("authorization" not in {key.lower() for key in item["headers"]} for item in calls)
    assert all(item["method"] == "GET" for item in calls)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a",
        "https://github.com.evil.invalid/a",
        "https://evil.invalid/a",
        "https://token@github.com/a",
        "https://u:p@github.com/a",
        "https://github.com:444/a",
        "https://github.com:wrong/a",
        "https://github.com/a#fragment",
        "https://github.com",
        "https://github.com/a\r\nAuthorization:x",
    ],
)
def test_redirect_poison_is_refused_before_another_request(monkeypatch, url) -> None:
    calls = _transport(monkeypatch, [Response(302, [("Location", url)])])
    with pytest.raises(ValueError):
        download.download_archive()
    assert len(calls) == 1 and calls[0]["closed"]


@pytest.mark.parametrize("headers", [[], [("Location", "/a"), ("Location", "/b")]])
def test_redirect_requires_one_unambiguous_location(monkeypatch, headers) -> None:
    calls = _transport(monkeypatch, [Response(301, headers)])
    with pytest.raises(ValueError, match="ambiguous"):
        download.download_archive()
    assert calls[0]["closed"]


def test_redirect_chain_cannot_make_a_fourth_request(monkeypatch) -> None:
    calls = _transport(monkeypatch, [Response(302, [("Location", "/again")]) for _ in range(3)])
    with pytest.raises(ValueError, match="redirect budget"):
        download.download_archive()
    assert len(calls) == 3 and all(item["closed"] for item in calls)


def test_error_status_is_not_interpreted_as_an_archive(monkeypatch) -> None:
    calls = _transport(monkeypatch, [Response(403, [], b"not an archive")])
    with pytest.raises(ValueError, match="response failed"):
        download.download_archive()
    assert calls[0]["closed"]


@pytest.mark.parametrize(
    "headers,body",
    [
        ([], b"abc"),
        ([("Content-Length", "4")], b"abc"),
        ([("Content-Length", "3"), ("Content-Length", "3")], b"abc"),
        ([("Content-Length", "3"), ("Transfer-Encoding", "chunked")], b"abc"),
        ([("Content-Length", "3"), ("Content-Encoding", "gzip")], b"abc"),
        ([("Content-Length", "3")], b"ab"),
        ([("Content-Length", "3")], b"abcd"),
        ([("Content-Length", "3")], b"xyz"),
    ],
)
def test_body_bounds_and_digest_are_mandatory(monkeypatch, headers, body) -> None:
    _pin(monkeypatch, b"abc")
    calls = _transport(monkeypatch, [Response(200, headers, body)])
    with pytest.raises(ValueError):
        download.download_archive()
    assert calls[0]["closed"]


def test_download_absolute_timer_interrupts_and_restores_signal_handler() -> None:
    previous = signal.getsignal(signal.SIGALRM)
    with pytest.raises(TimeoutError, match="total wall-clock"), download.download_deadline():
        signal.raise_signal(signal.SIGALRM)
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_download_does_not_overwrite_an_existing_timer(monkeypatch) -> None:
    monkeypatch.setattr(download.signal, "getitimer", lambda _kind: (2.0, 0.0))
    with pytest.raises(ValueError, match="another timer"), download.download_deadline():
        pytest.fail("existing timer was overwritten")


def test_only_the_regular_binary_is_extracted_after_digest_verification(
    tmp_path, monkeypatch
) -> None:
    raw = _archive(
        [("LICENSE", b"neutral", tarfile.REGTYPE), ("gitleaks", _elf(), tarfile.REGTYPE)]
    )
    _pin(monkeypatch, raw)
    monkeypatch.setattr(artifact, "download_archive", lambda: (raw, ["github.com"]))
    binary, identity = artifact.acquire_binary(tmp_path / "bin")
    assert binary.read_bytes() == _elf() and binary.stat().st_mode & 0o777 == 0o500
    assert list(binary.parent.iterdir()) == [binary]
    assert identity["binary_sha256"] == hashlib.sha256(_elf()).hexdigest()
    assert identity["source_build_attested"] is False
    assert identity["archive_members"] == [
        {"name": "LICENSE", "size": 7},
        {"name": "gitleaks", "size": 64},
    ]


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE]
)
def test_archive_nonregular_members_are_refused(tmp_path, monkeypatch, kind) -> None:
    raw = _archive([("gitleaks", b"", kind)])
    _pin(monkeypatch, raw)
    with pytest.raises(ValueError, match="unsafe"):
        artifact.extract_binary(raw, tmp_path / "bin")
    assert not (tmp_path / "bin").exists()


@pytest.mark.parametrize(
    "name", ["../gitleaks", "/gitleaks", "./gitleaks", "sub/gitleaks", "a\\gitleaks", ".", ".."]
)
def test_archive_path_aliases_and_traversal_are_refused(tmp_path, monkeypatch, name) -> None:
    raw = _archive([(name, _elf(), tarfile.REGTYPE)])
    _pin(monkeypatch, raw)
    with pytest.raises(ValueError, match="unsafe"):
        artifact.extract_binary(raw, tmp_path / "bin")


@pytest.mark.parametrize(
    "case", ["duplicate", "missing", "members", "expansion", "binary-size", "truncated"]
)
def test_archive_census_and_size_poison(tmp_path, monkeypatch, case) -> None:
    entries = [("gitleaks", _elf(), tarfile.REGTYPE)]
    if case == "duplicate":
        entries *= 2
    if case == "missing":
        entries = [("README", b"neutral", tarfile.REGTYPE)]
    if case == "members":
        entries += [(f"extra{index}", b"", tarfile.REGTYPE) for index in range(16)]
    raw = _archive(entries)
    _pin(monkeypatch, raw)
    if case == "expansion":
        monkeypatch.setattr(artifact, "MAX_EXPANDED", 100)
    if case == "binary-size":
        monkeypatch.setattr(artifact, "MAX_BINARY", 63)
    if case == "truncated":
        monkeypatch.setattr(tarfile.TarFile, "extractfile", lambda *_: io.BytesIO(b"short"))
    with pytest.raises(ValueError):
        artifact.extract_binary(raw, tmp_path / "bin")


@pytest.mark.parametrize("offset,value", [(0, 0), (4, 1), (5, 2), (16, 0), (18, 3)])
def test_binary_must_be_the_expected_elf_architecture(tmp_path, monkeypatch, offset, value) -> None:
    binary = bytearray(_elf())
    binary[offset] = value
    raw = _archive([("gitleaks", bytes(binary), tarfile.REGTYPE)])
    _pin(monkeypatch, raw)
    with pytest.raises(ValueError, match="ELF64"):
        artifact.extract_binary(raw, tmp_path / "bin")


def test_wrong_archive_never_reaches_decompression(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        artifact.gzip, "GzipFile", lambda **_: pytest.fail("unverified decompression")
    )
    with pytest.raises(ValueError, match="size"):
        artifact.extract_binary(b"not the pinned asset", tmp_path / "bin")


def test_archive_digest_mismatch_stops_before_any_archive_inspection(tmp_path, monkeypatch) -> None:
    raw = _archive([("gitleaks", _elf(), tarfile.REGTYPE)])
    _pin(monkeypatch, raw)
    monkeypatch.setattr(download, "ARCHIVE_SHA256", "0" * 64)
    monkeypatch.setattr(
        artifact.gzip, "GzipFile", lambda **_: pytest.fail("unverified decompression")
    )
    with pytest.raises(ValueError, match="digest"):
        artifact.extract_binary(raw, tmp_path / "bin")
    assert not (tmp_path / "bin").exists()
