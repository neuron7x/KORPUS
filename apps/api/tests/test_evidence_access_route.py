from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/evidence_access_route.py"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("evidence_access_route", SCRIPT)
assert SPEC and SPEC.loader
ROUTES = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ROUTES
SPEC.loader.exec_module(ROUTES)
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "validate_evidence_refusal", ROOT / "scripts/validate_evidence_refusal.py"
)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
sys.modules[VALIDATOR_SPEC.name] = VALIDATOR
VALIDATOR_SPEC.loader.exec_module(VALIDATOR)


def _source(**changes: object) -> dict[str, object]:
    source: dict[str, object] = {
        "id": "SOURCE",
        "canonical_title": "Ukrainian Unmanned Aerial System Tactics",
        "issuer": "US Army TRADOC G-2",
        "source_uri": "https://official.example/product",
        "ingestible": True,
    }
    source.update(changes)
    return source


def _external(**changes: object) -> dict[str, object]:
    route: dict[str, object] = {
        "class": "external_vantage_fetch",
        "status": "retrieved",
        "uri": "https://official.example/document.pdf",
        "media_type": "application/pdf",
        "pages": 5,
        "document_title": "Ukrainian Unmanned Aerial System Tactics",
        "issuer": "US Army TRADOC G-2",
        "observed_on": date.today().isoformat(),
        "access_vantage": "separate web fetch",
        "limitation": "Does not prove that the deployment host can retrieve the file.",
    }
    route.update(changes)
    return route


def test_recognises_a_reciprocal_captured_copy() -> None:
    source = _source(same_publication_as=["COPY"])
    copy = _source(
        id="COPY",
        source_uri="https://other.example/document.pdf",
        same_publication_as=["SOURCE"],
        capture={
            "uri": "https://other.example/document.pdf",
            "text_as_extracted": {"sha256": "a" * 64},
        },
        integrity_anchor={"sha256": "b" * 64},
    )
    assert ROUTES.access_route(source, {"SOURCE": source, "COPY": copy}) == (True, [])


def test_one_way_captured_copy_is_not_an_access_route() -> None:
    source = _source(same_publication_as=["COPY"])
    copy = _source(
        id="COPY",
        source_uri="https://other.example/document.pdf",
        same_publication_as=[],
        capture={
            "uri": "https://other.example/document.pdf",
            "text_as_extracted": {"sha256": "a" * 64},
        },
        integrity_anchor={"sha256": "b" * 64},
    )
    assert ROUTES.access_route(source, {"SOURCE": source, "COPY": copy}) == (False, [])


def test_non_list_reverse_link_fails_closed() -> None:
    source = _source(same_publication_as=["COPY"])
    copy = _source(id="COPY", same_publication_as=None)
    assert ROUTES.access_route(source, {"SOURCE": source, "COPY": copy}) == (False, [])


def test_recognises_a_recent_external_vantage_fetch() -> None:
    source = _source(alternate_access=_external())
    assert ROUTES.access_route(source, {"SOURCE": source}) == (True, [])


def test_recent_external_route_lifts_only_an_aged_vantage_gap() -> None:
    source = _source(
        alternate_access=_external(),
        evidence_refusal={
            "class": "host_unreachable_from_here",
            "reason": "HTTP 000 from this deployment host",
            "retryable": False,
            "observed_on": (date.today() - timedelta(days=31)).isoformat(),
        },
    )
    assert VALIDATOR.problems([source]) == []

    source["evidence_refusal"] = {
        "class": "extractor_refused",
        "reason": "our extractor rejected the artifact",
        "retryable": False,
        "observed_on": date.today().isoformat(),
    }
    assert "our own extractor" in " ".join(VALIDATOR.problems([source]))


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"class": "note"}, ".class"),
        ({"status": "seen_in_search"}, ".status"),
        ({"uri": "http://official.example/document.pdf"}, ".uri"),
        ({"media_type": "image/png"}, ".media_type"),
        ({"pages": True}, ".pages"),
        ({"pages": 0}, ".pages"),
        ({"access_vantage": " "}, ".access_vantage"),
        ({"limitation": ""}, ".limitation"),
        ({"observed_on": "yesterday"}, ".observed_on"),
        ({"observed_on": (date.today() + timedelta(days=1)).isoformat()}, "future"),
        (
            {
                "observed_on": (
                    date.today() - timedelta(days=ROUTES.EXTERNAL_ROUTE_MAX_AGE_DAYS + 1)
                ).isoformat()
            },
            "maximum",
        ),
    ],
)
def test_malformed_or_stale_external_observation_fails_closed(
    change: dict[str, object], fragment: str
) -> None:
    source = _source(alternate_access=_external(**change))
    found, failures = ROUTES.access_route(source, {"SOURCE": source})
    assert not found
    assert any(fragment in failure for failure in failures)


def test_non_object_external_observation_fails_closed() -> None:
    source = _source(alternate_access="retrieved")
    assert ROUTES.access_route(source, {"SOURCE": source}) == (
        False,
        ["SOURCE: alternate_access is not an object"],
    )
