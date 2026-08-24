"""The browser session envelope must refuse everything it did not issue.

The access token lives inside an AES-GCM envelope the browser cannot read, so every
rejection here is what stands between a cookie and an authenticated request: a forged
envelope, one sealed for a different purpose, one that expired, one whose base64 was
re-encoded on the way. Coverage recorded those branches as never taken.

The cross-kind case is the one worth naming. `seal` binds the envelope kind as
associated data, so a state envelope must not open as a session envelope — otherwise
the value handed out before login would be accepted as proof of login.
"""

from __future__ import annotations

import pytest
from korpus.security.browser_oidc import BrowserSessionCodec, BrowserSessionError

SECRET = "browser-session-secret-for-tests-0123456789"


def _codec(now: float = 1_800_000_000.0) -> BrowserSessionCodec:
    return BrowserSessionCodec(SECRET, clock=lambda: now)


def test_a_sealed_session_opens_with_its_payload() -> None:
    """The dual: the refusals below mean nothing if nothing round-trips."""
    codec = _codec()
    token = codec.seal("session", {"access_token": "abc", "csrf": "xyz"}, ttl_seconds=600)

    assert codec.open(token, expected_kind="session") == {"access_token": "abc", "csrf": "xyz"}


def test_a_short_secret_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 32 characters"):
        BrowserSessionCodec("too-short")


@pytest.mark.parametrize("kind,ttl", [("", 600), ("session", 0), ("session", -1)])
def test_an_envelope_that_could_not_be_valid_is_refused_at_seal(kind: str, ttl: int) -> None:
    with pytest.raises(ValueError, match="invalid browser session envelope"):
        _codec().seal(kind, {}, ttl_seconds=ttl)


def test_an_envelope_sealed_for_another_purpose_does_not_open_as_a_session() -> None:
    """The pre-login state value must not be accepted as proof of login."""
    codec = _codec()
    state = codec.seal("state", {"nonce": "n"}, ttl_seconds=600)

    with pytest.raises(BrowserSessionError, match="authentication failed"):
        codec.open(state, expected_kind="session")


def test_an_envelope_from_another_secret_is_refused() -> None:
    other = BrowserSessionCodec("a-completely-different-secret-0123456789", clock=lambda: 1e9)
    forged = other.seal("session", {"access_token": "attacker"}, ttl_seconds=600)

    with pytest.raises(BrowserSessionError, match="authentication failed"):
        _codec(1e9).open(forged, expected_kind="session")


def test_a_tampered_ciphertext_is_refused() -> None:
    codec = _codec()
    token = codec.seal("session", {"access_token": "abc"}, ttl_seconds=600)
    flipped = token[:-2] + ("AA" if not token.endswith("AA") else "AB")

    with pytest.raises(BrowserSessionError):
        codec.open(flipped, expected_kind="session")


@pytest.mark.parametrize("token", ["", "!!!not-base64!!!", "AAAA"])
def test_a_malformed_envelope_is_refused(token: str) -> None:
    with pytest.raises(BrowserSessionError):
        _codec().open(token, expected_kind="session")


def test_an_expired_session_is_refused() -> None:
    issued = _codec(1_800_000_000.0).seal("session", {"access_token": "abc"}, ttl_seconds=60)
    later = _codec(1_800_000_000.0 + 61)

    with pytest.raises(BrowserSessionError, match="expired or not yet valid"):
        later.open(issued, expected_kind="session")


def test_a_session_issued_in_the_future_is_refused() -> None:
    """Beyond the small skew allowance, a future iat is not a session we issued."""
    issued = _codec(1_800_000_000.0 + 3600).seal("session", {"access_token": "a"}, ttl_seconds=600)
    earlier = _codec(1_800_000_000.0)

    with pytest.raises(BrowserSessionError, match="expired or not yet valid"):
        earlier.open(issued, expected_kind="session")
