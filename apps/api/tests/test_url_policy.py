from __future__ import annotations

import pytest
from korpus.security.external_destination import parse_external_https_url
from korpus.security.url_policy import (
    is_explicit_loopback_http_origin,
    is_explicit_loopback_http_url,
    is_https_url,
    parse_http_url,
    parse_https_url,
)


def test_https_policy_accepts_unambiguous_https_urls() -> None:
    assert parse_https_url("https://example.com/v1?q=1").hostname == "example.com"
    assert is_https_url("https://[2001:db8::1]:8443/v1") is True


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com",
        "https://user@example.com",
        "https://user:pass@example.com",
        "https://example.com/path#fragment",
        "https://example.com\\@evil.example/",
        " https://example.com",
        "https://example.com\n",
        "https://example.com:bad/path",
        "https:///missing-host",
    ],
)
def test_https_policy_refuses_ambiguous_or_credential_bearing_urls(value: str) -> None:
    with pytest.raises(ValueError):
        parse_https_url(value)
    assert is_https_url(value) is False


def test_origin_policy_refuses_path_and_query() -> None:
    assert is_https_url("https://example.com", origin_only=True) is True
    assert is_https_url("https://example.com/", origin_only=True) is True
    assert is_https_url("https://example.com/path", origin_only=True) is False
    assert is_https_url("https://example.com/?x=1", origin_only=True) is False


def test_loopback_http_policy_is_exact_not_prefix_based() -> None:
    assert is_explicit_loopback_http_url("http://127.0.0.1:8080/callback") is True
    assert is_explicit_loopback_http_url("http://localhost:8080/v1?q=1") is True
    assert is_explicit_loopback_http_url("http://testserver/v1/auth/callback") is True
    assert is_explicit_loopback_http_url("http://localhost.evil.example/v1") is False
    assert is_explicit_loopback_http_url("http://localhost@evil.example/v1") is False
    assert is_explicit_loopback_http_url("http://user@localhost/v1") is False
    assert is_explicit_loopback_http_url("http://169.254.169.254/latest/meta-data") is False


def test_loopback_origin_policy_refuses_callback_paths() -> None:
    assert is_explicit_loopback_http_origin("http://localhost:8080") is True
    assert is_explicit_loopback_http_origin("http://localhost:8080/") is True
    assert is_explicit_loopback_http_origin("http://localhost:8080/callback") is False
    assert is_explicit_loopback_http_origin("http://localhost:8080/?x=1") is False


def test_generic_http_parser_rejects_non_http_and_fragments() -> None:
    assert parse_http_url("http://10.0.0.5:11434/v1", allow_query=False).hostname == "10.0.0.5"
    for value in ("file:///etc/passwd", "gopher://localhost", "http://localhost/#x"):
        with pytest.raises(ValueError):
            parse_http_url(value)


@pytest.mark.parametrize(
    "value",
    [
        "https://localhost/v1",
        "https://service.localhost/v1",
        "https://127.0.0.1/v1",
        "https://10.0.0.1/v1",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/v1",
        "https://[fd00::1]/v1",
        "https://[fe80::1]/v1",
        "https://0.0.0.0/v1",
    ],
)
def test_external_https_policy_refuses_non_global_literal_destinations(value: str) -> None:
    with pytest.raises(ValueError):
        parse_external_https_url(value)


def test_external_https_policy_accepts_dns_and_global_literals() -> None:
    assert parse_external_https_url("https://api.example.com/v1").hostname == "api.example.com"
    assert parse_external_https_url("https://93.184.216.34/v1").hostname == "93.184.216.34"
