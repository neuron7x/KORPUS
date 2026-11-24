"""Fetch one digest-pinned public release, without credentials or implicit redirects."""

from __future__ import annotations

import hashlib
import http.client
import signal
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType
from urllib.parse import urljoin, urlsplit

from scripts.source_security_contract import require

RELEASE_URL = (
    "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/"
    "gitleaks_8.30.1_linux_x64.tar.gz"
)
ARCHIVE_SIZE = 8_230_402
ARCHIVE_SHA256 = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
ALLOWED_HOSTS = frozenset(
    {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
)
DOWNLOAD_SECONDS = 45


def _expired(_signum: int, _frame: FrameType | None) -> None:
    raise TimeoutError("fixed release download exceeded its total wall-clock budget")


@contextmanager
def download_deadline() -> Iterator[None]:
    """Linux main-thread timer also bounds slow headers and byte-by-byte responses."""
    require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "another timer is active")
    previous = signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, DOWNLOAD_SECONDS)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def download_target(url: str) -> tuple[str, str]:
    require(all(32 < ord(character) < 127 for character in url), "non-ASCII or control byte in URL")
    parsed = urlsplit(url)
    require(
        parsed.scheme == "https"
        and parsed.hostname in ALLOWED_HOSTS
        and parsed.port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and parsed.path.startswith("/"),
        "release redirect is outside the fixed HTTPS host boundary",
    )
    assert parsed.hostname is not None
    return parsed.hostname, parsed.path + ("?" + parsed.query if parsed.query else "")


def verify_archive(raw: bytes) -> None:
    require(len(raw) == ARCHIVE_SIZE, "release archive size differs from the pinned asset")
    require(
        hashlib.sha256(raw).hexdigest() == ARCHIVE_SHA256,
        "release archive digest differs from the pinned asset",
    )


def _body(response: http.client.HTTPResponse) -> bytes:
    headers = response.getheaders()
    lengths = [value for name, value in headers if name.lower() == "content-length"]
    require(lengths == [str(ARCHIVE_SIZE)], "ambiguous or unexpected release Content-Length")
    require(
        all(
            name.lower() != "transfer-encoding"
            and (name.lower() != "content-encoding" or value.lower() == "identity")
            for name, value in headers
        ),
        "encoded or chunked release response is refused",
    )
    raw = bytearray()
    while len(raw) <= ARCHIVE_SIZE:
        chunk = response.read1(min(65_536, ARCHIVE_SIZE + 1 - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
    result = bytes(raw)
    verify_archive(result)
    return result


def download_archive() -> tuple[bytes, list[str]]:
    """At most three HTTPS requests, two redirects, 45 seconds, and pinned bytes."""
    url = RELEASE_URL
    hosts: list[str] = []
    with download_deadline():
        while True:
            require(len(hosts) < 3, "release response exceeded the redirect budget")
            host, target = download_target(url)
            hosts.append(host)
            connection = http.client.HTTPSConnection(
                host, timeout=10, context=ssl.create_default_context()
            )
            try:
                connection.request(
                    "GET",
                    target,
                    headers={
                        "Accept": "application/octet-stream",
                        "Accept-Encoding": "identity",
                        "User-Agent": "korpus-nonauthoritative-engine-diagnostic",
                    },
                )
                response = connection.getresponse()
                if response.status == 200:
                    return _body(response), hosts
                require(
                    response.status in {301, 302, 303, 307, 308},
                    "release response failed",
                )
                locations = [
                    value for name, value in response.getheaders() if name.lower() == "location"
                ]
                require(len(locations) == 1, "ambiguous release redirect")
                require(
                    all(32 < ord(character) < 127 for character in locations[0]),
                    "non-ASCII or control byte in redirect",
                )
                url = urljoin(url, locations[0])
                download_target(url)
            finally:
                connection.close()
