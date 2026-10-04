"""Validate evidence that an unreachable source has another access route.

The result is deliberately narrower than "the source is ingestible here".  It only
refutes the claim that nobody found another route: either the same publication is
already captured under a reciprocal catalogue identity, or a recent external network
vantage retrieved the artifact and recorded the limitation explicitly.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlparse

EXTERNAL_ROUTE_CLASS = "external_vantage_fetch"
EXTERNAL_ROUTE_STATUS = "retrieved"
EXTERNAL_ROUTE_MAX_AGE_DAYS = 30
MEDIA_TYPES = {"application/pdf", "text/html"}


def _captured_peer(entry: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> bool:
    identifier = entry.get("id")
    peers = entry.get("same_publication_as")
    if not isinstance(peers, list) or not peers:
        return False
    for peer_id in peers:
        peer = by_id.get(str(peer_id))
        if not isinstance(peer, dict):
            continue
        peer_links = peer.get("same_publication_as")
        if not isinstance(peer_links, list) or identifier not in peer_links:
            continue
        capture = peer.get("capture")
        anchor = peer.get("integrity_anchor")
        if (
            peer.get("ingestible") is True
            and isinstance(capture, dict)
            and capture.get("uri") == peer.get("source_uri")
            and isinstance(capture.get("text_as_extracted"), dict)
            and bool(capture["text_as_extracted"].get("sha256"))
            and isinstance(anchor, dict)
            and bool(anchor.get("sha256"))
        ):
            return True
    return False


def _external_route(entry: dict[str, Any], today: date) -> tuple[bool, list[str]]:
    route = entry.get("alternate_access")
    identifier = str(entry.get("id", "<no id>"))
    if route is None:
        return False, []
    if not isinstance(route, dict):
        return False, [f"{identifier}: alternate_access is not an object"]
    failures: list[str] = []
    expected = {
        "class": EXTERNAL_ROUTE_CLASS,
        "status": EXTERNAL_ROUTE_STATUS,
        "document_title": entry.get("canonical_title"),
        "issuer": entry.get("issuer"),
    }
    for field, value in expected.items():
        if route.get(field) != value:
            failures.append(f"{identifier}: alternate_access.{field} must equal {value!r}")
    uri = str(route.get("uri", ""))
    parsed = urlparse(uri)
    if parsed.scheme != "https" or not parsed.netloc:
        failures.append(f"{identifier}: alternate_access.uri must be an absolute HTTPS URI")
    if route.get("media_type") not in MEDIA_TYPES:
        failures.append(
            f"{identifier}: alternate_access.media_type is not a supported document type"
        )
    pages = route.get("pages")
    if isinstance(pages, bool) or not isinstance(pages, int) or pages <= 0:
        failures.append(f"{identifier}: alternate_access.pages must be a positive integer")
    for field in ("access_vantage", "limitation"):
        if not str(route.get(field, "")).strip():
            failures.append(f"{identifier}: alternate_access.{field} must be non-empty")
    try:
        age = (today - date.fromisoformat(str(route.get("observed_on")))).days
    except ValueError:
        failures.append(f"{identifier}: alternate_access.observed_on is not an ISO date")
    else:
        if age < 0:
            failures.append(f"{identifier}: alternate_access.observed_on is in the future")
        if age > EXTERNAL_ROUTE_MAX_AGE_DAYS:
            failures.append(
                f"{identifier}: alternate_access is {age} days old; maximum is "
                f"{EXTERNAL_ROUTE_MAX_AGE_DAYS}"
            )
    return not failures, failures


def access_route(
    entry: dict[str, Any], by_id: dict[str, dict[str, Any]], today: date | None = None
) -> tuple[bool, list[str]]:
    """Return whether a route is evidenced and any malformed-evidence failures."""

    if _captured_peer(entry, by_id):
        return True, []
    return _external_route(entry, today or date.today())
