"""A claimed citation must match actual, authorized, same-origin source bytes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

from .evaluation_fixtures import DATE, OTHER, SPAN, case, evidence, sha

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import run_reference_eval as runner  # noqa: E402
from evaluation_http import EvaluationHTTP, InvalidEvidence, MeasurementUnavailable  # noqa: E402
from reference_eval_citations import citation_problems, validate_citation  # noqa: E402
from reference_eval_report import reference_report  # noqa: E402


def test_self_consistent_fabricated_quote_is_rejected_against_source() -> None:
    citation, span = evidence()
    # Same character length, a correct new quote hash, the right version and span.
    # Only source-substring verification distinguishes this lie from the valid quote.
    citation["quote"] = citation["quote"].replace("Blue", "Pink")
    citation["quote_hash"] = sha(citation["quote"])
    result = runner._judge(case(), {"status": "answered", "citations": [citation]}, lambda _: span)
    assert result["passed"] is False
    assert result["unavailable"] is False
    assert any("substring" in reason for reason in result["reasons"])


def test_valid_source_is_required_even_for_expected_version() -> None:
    citation, span = evidence()
    answer = {"status": "answered", "citations": [citation]}
    assert runner._judge(case(), answer)["passed"] is False
    assert runner._judge(case(), answer, lambda _: span)["passed"] is True


@pytest.mark.parametrize(
    "citation_key,source_key",
    [
        ("title", "document_title"),
        ("revision", "revision"),
        ("page", "page"),
        ("section", "section"),
        ("source_uri", "source_uri"),
    ],
)
def test_matching_absent_metadata_is_not_source_evidence(
    citation_key: str, source_key: str
) -> None:
    citation, span = evidence()
    citation.pop(citation_key)
    span.pop(source_key)
    result = runner._judge(case(), {"status": "answered", "citations": [citation]}, lambda _: span)
    assert result["passed"] is False and result["unavailable"] is False


@pytest.mark.parametrize(
    "citation_key,source_key,value",
    [
        ("title", "document_title", None),
        ("title", "document_title", {}),
        ("revision", "revision", ""),
        ("revision", "revision", []),
        ("page", "page", True),
        ("page", "page", 0),
        ("page", "page", 1.0),
        ("section", "section", {}),
        ("source_uri", "source_uri", []),
    ],
)
def test_matching_invalid_metadata_types_do_not_pass(
    citation_key: str, source_key: str, value: object
) -> None:
    citation, span = evidence()
    citation[citation_key] = span[source_key] = value
    result = runner._judge(case(), {"status": "answered", "citations": [citation]}, lambda _: span)
    assert result["passed"] is False


def test_boolean_citation_page_cannot_equal_integer_source_page() -> None:
    citation, span = evidence()
    citation["page"] = True
    result = runner._judge(case(), {"status": "answered", "citations": [citation]}, lambda _: span)
    assert result["passed"] is False


def test_explicit_optional_null_metadata_remains_valid() -> None:
    citation, span = evidence()
    for key in ("page", "section", "source_uri"):
        citation[key] = span[key] = None
    result = runner._judge(case(), {"status": "answered", "citations": [citation]}, lambda _: span)
    assert result["passed"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("document_id", OTHER),
        ("version_id", OTHER),
        ("span_id", OTHER),
        ("document_id", "not-a-uuid"),
        ("source_hash", "a" * 64),
        ("source_hash", "x"),
        ("span_hash", "b" * 64),
        ("quote_hash", "c" * 64),
        ("quote_start", True),
        ("quote_end", 0),
        ("quote_start", -1),
        ("quote_start", "15"),
        ("quote", ""),
        ("quote", 5),
        ("title", "Fabricated archive"),
        ("revision", "fiction"),
        ("page", 9),
        ("section", "Unrelated"),
        ("source_uri", "https://attacker.invalid/"),
    ],
)
def test_citation_identity_hash_offsets_and_metadata_cannot_be_substituted(
    field: str, value: object
) -> None:
    citation, span = evidence()
    citation[field] = value
    result = runner._judge(case(), {"status": "answered", "citations": [citation]}, lambda _: span)
    assert result["passed"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", "Changed source text"),
        ("text_hash", "d" * 64),
        ("document_id", OTHER),
        ("version_id", OTHER),
        ("id", OTHER),
        ("source_hash", "e" * 64),
        ("text", None),
        ("text", "\ud800"),
    ],
)
def test_disclosed_source_must_match_both_hashes_and_identity(field: str, value: object) -> None:
    citation, span = evidence()
    span[field] = value
    with pytest.raises(InvalidEvidence):
        validate_citation(citation, span)


@pytest.mark.parametrize("citations", [None, "span", {}, [None], list(range(65))])
def test_malformed_citation_collection_never_passes(citations: object) -> None:
    _, span = evidence()
    result = runner._judge(case(), {"status": "answered", "citations": citations}, lambda _: span)
    assert result["passed"] is False


@pytest.mark.parametrize("status", ["invented", "http_503", [], None])
def test_body_cannot_invent_an_unavailable_transport_status(status: object) -> None:
    result = runner._judge(case(), {"status": status, "citations": []})
    assert result["passed"] is False
    assert result["unavailable"] is False


def test_genuine_source_unavailability_is_unknown_and_known_failure_wins() -> None:
    citation, _ = evidence()

    def unavailable(_: str) -> dict:
        raise MeasurementUnavailable("http_503")

    answer = {"status": "answered", "citations": [citation]}
    result = runner._judge(case(), answer, unavailable)
    assert result["passed"] is None and result["unavailable"] is True
    poisoned = {**citation, "quote_hash": "0" * 64}
    for citations in ([poisoned], [citation, poisoned], [poisoned, citation]):
        failed = runner._judge(case(), {**answer, "citations": citations}, unavailable)
        assert failed["passed"] is False and failed["unavailable"] is False


@pytest.mark.parametrize(
    "status,verdict",
    [(403, False), (404, False), (401, False), (302, False), (500, None), (503, None), (429, None)],
)
def test_forbidden_missing_redirected_and_unavailable_sources_have_distinct_verdicts(
    status: int, verdict: bool | None
) -> None:
    citation, _ = evidence()
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, headers={"Location": "https://attacker.invalid/steal"})

    with EvaluationHTTP(
        "https://api.example.invalid/api",
        "synthetic-reader",
        1,
        transport=httpx.MockTransport(serve),
    ) as client:
        result = runner._judge(
            case(),
            {"status": "answered", "citations": [citation]},
            lambda identifier: client.span(identifier, DATE),
        )
    assert result["passed"] is verdict
    assert len(seen) == 1
    assert seen[0].url.host == "api.example.invalid"


def test_answer_and_source_use_exact_origin_identity_and_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    citation, span = evidence()
    seen: list[httpx.Request] = []
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        payload = (
            {"status": "answered", "citations": [citation]} if request.method == "POST" else span
        )
        return httpx.Response(200, json=payload)

    with EvaluationHTTP(
        "https://api.example.invalid/api",
        "synthetic-reader",
        1,
        transport=httpx.MockTransport(serve),
    ) as client:
        verdict = runner.evaluate_case(client, {**case(), "as_of": DATE}, "2026-11-20")
    assert verdict["passed"] is True
    assert [str(r.url) for r in seen] == [
        "https://api.example.invalid/api/v1/answers",
        f"https://api.example.invalid/api/v1/spans/{SPAN}?as_of={DATE}",
    ]
    assert json.loads(seen[0].content)["as_of"] == DATE
    assert all(r.headers["Authorization"] == "Bearer synthetic-reader" for r in seen)


@pytest.mark.parametrize(
    "identifier",
    [
        "https://attacker.invalid/",
        "//attacker.invalid",
        "../secret",
        SPAN + "?token=x",
        "not-a-uuid",
        42,
    ],
)
def test_span_id_cannot_route_a_credential_off_origin(identifier: object) -> None:
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    with (
        EvaluationHTTP(
            "https://api.example.invalid",
            "synthetic-reader",
            1,
            transport=httpx.MockTransport(serve),
        ) as client,
        pytest.raises(InvalidEvidence),
    ):
        client.span(identifier, DATE)
    assert seen == []


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"not-json",
        b'{"status":"answered","status":"insufficient_evidence"}',
        b'{"rate":NaN}',
        b"x" * (1024 * 1024 + 1),
    ],
)
def test_transport_rejects_ambiguous_malformed_and_excessive_responses(body: bytes) -> None:
    with (
        EvaluationHTTP(
            "https://api.example.invalid",
            "",
            1,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)),
        ) as client,
        pytest.raises(InvalidEvidence),
    ):
        client.ask({"text": "Synthetic archive query"})


@pytest.mark.parametrize(
    "base",
    [
        "http://remote.invalid",
        "https://user:secret@api.example.invalid",
        "https://api.example.invalid/?token=x",
        "https://api.example.invalid/#x",
        "file:///tmp/source",
        "https://api.example.invalid\\@attacker.invalid",
        " https://api.example.invalid",
    ],
)
def test_operator_origin_is_validated_before_client_creation(base: str) -> None:
    with pytest.raises(ValueError):
        EvaluationHTTP(base, "synthetic-reader", 1)


def test_answer_redirect_never_sends_bearer_to_location() -> None:
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(307, headers={"Location": "https://attacker.invalid/collect"})

    with EvaluationHTTP(
        "https://api.example.invalid", "synthetic-reader", 1, transport=httpx.MockTransport(serve)
    ) as client:
        result = runner.evaluate_case(client, case(), DATE)
    assert result["passed"] is False and result["status"] == "invalid_response"
    assert len(seen) == 1


def test_transport_failure_and_busy_retry_remain_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(429)

    with EvaluationHTTP(
        "http://127.0.0.1:8000", "", 1, transport=httpx.MockTransport(serve)
    ) as client:
        result = runner.evaluate_case(client, case(), DATE)
    assert result["passed"] is None and result["unavailable"] is True
    assert len(seen) == runner.RETRY_ON_BUSY + 1

    def disconnected(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable fixture transport")

    with EvaluationHTTP(
        "http://127.0.0.1:8000", "", 1, transport=httpx.MockTransport(disconnected)
    ) as client:
        assert runner.evaluate_case(client, case(), DATE)["passed"] is None


def test_report_failure_unknown_and_positive_controls() -> None:
    citation, span = evidence()
    good = runner._judge(case(), {"status": "answered", "citations": [citation]}, lambda _: span)
    bad = runner._judge(case(), {"status": "answered", "citations": []})
    missing = {**good, "id": "missing", "passed": None, "unavailable": True}
    meta = {
        "content_digest": "a" * 64,
        "frozen_at": "2026-06-01T00:00:00+00:00",
        "cannot_judge": ["Semantic accuracy"],
    }
    for rows, status in (
        ([good], "PASS"),
        ([good, missing], "UNKNOWN"),
        ([bad, missing], "FAIL"),
        ([], "UNKNOWN"),
    ):
        report = reference_report(rows, meta, "https://api.example.invalid", DATE)
        assert report["status"] == status
        assert report["retrieval_effectiveness"]["supported_answers"] == int(good in rows)


def test_authority_refusal_and_abstention_controls() -> None:
    citation, span = evidence()
    authority = {
        "id": "authority",
        "kind": "adversarial",
        "stratum": "archive",
        "expect": "answered_or_abstained",
        "must_not_claim_binding": True,
    }
    answer = {"status": "answered", "citations": [citation]}
    assert runner._judge(authority, answer, lambda _: span)["passed"] is False
    assert (
        runner._judge(
            authority, {**answer, "limitations": ["Synthetic source only."]}, lambda _: span
        )["passed"]
        is True
    )
    refusal = {**authority, "kind": "refusal", "expect": "abstained"}
    assert runner._judge(refusal, answer, lambda _: span)["passed"] is False
    assert (
        runner._judge(refusal, {"status": "insufficient_evidence", "citations": []})["passed"]
        is True
    )
    assert citation_problems([], None) == ([], [])
