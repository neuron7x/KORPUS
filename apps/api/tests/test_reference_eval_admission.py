"""A reference result cannot outlive or misidentify the input it actually executed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

from .evaluation_fixtures import case, evidence, freeze_reference

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import run_reference_eval as runner  # noqa: E402
from evaluation_http import EvaluationHTTP  # noqa: E402
from evaluation_json import jsonl_rows, read_bounded, strict_json  # noqa: E402
from reference_eval_set import load_reference_set  # noqa: E402


def _run_without_network(path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("evaluation contacted HTTP before admitting its actual frozen set")

    monkeypatch.setattr(runner, "EvaluationHTTP", forbidden)
    monkeypatch.setattr(sys, "argv", ["reference-eval", "--set", str(path)])
    return runner.main()


def test_changed_reference_query_is_rejected_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "reference.jsonl"
    freeze_reference(path)
    row = case()
    row["query"] = "Which label is green?"
    path.write_text(json.dumps(row) + "\n")
    assert _run_without_network(path, monkeypatch) == 2


@pytest.mark.parametrize(
    "poison",
    [
        "empty",
        "duplicate",
        "unknown-kind",
        "unknown-field",
        "empty-query",
        "bad-expect",
        "invalid-date",
        "holders-empty",
        "holders-duplicate",
        "holder-url",
        "sampled-wrong",
        "missing-evidence",
        "binding-string",
    ],
)
def test_reference_case_schema_is_checked_before_http(
    poison: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "reference.jsonl"
    row = case()
    mutations = {
        "unknown-kind": {"kind": "invented"},
        "unknown-field": {"trusted": True},
        "empty-query": {"query": " "},
        "bad-expect": {"expect": "always-pass"},
        "invalid-date": {"as_of": "2026-02-31"},
        "holders-empty": {"must_cite_one_of_if_answered": []},
        "holders-duplicate": {"must_cite_one_of_if_answered": [row["sampled_from_version"]] * 2},
        "holder-url": {"must_cite_one_of_if_answered": ["https://untrusted.invalid/"]},
        "sampled-wrong": {"sampled_from_version": "missing"},
        "binding-string": {"kind": "adversarial", "must_not_claim_binding": "false"},
    }
    row.update(mutations.get(poison, {}))
    if poison == "missing-evidence":
        row.pop("evidence_sentence")
    rows = [] if poison == "empty" else ([row, row.copy()] if poison == "duplicate" else [row])
    freeze_reference(path, rows)
    assert _run_without_network(path, monkeypatch) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("cases", True),
        ("cases", 2),
        ("content_digest", "f" * 16),
        ("content_digest", "a" * 64),
        ("strata", 2),
        ("strata", True),
        ("by_kind", {"invented": 1}),
        ("by_kind", {"retrieval": True}),
        ("by_kind", {"retrieval": 2}),
        ("cannot_judge", []),
        ("frozen_at", "2026-06-01"),
    ],
)
def test_reference_metadata_poison_is_rejected_before_http(
    field: str, value: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "reference.jsonl"
    meta = freeze_reference(path)
    meta[field] = value
    path.with_suffix(".meta.json").write_text(json.dumps(meta))
    assert _run_without_network(path, monkeypatch) == 2


@pytest.mark.parametrize(
    "body", [b'{"id":"a","id":"b"}', b'{"x":NaN}', b'{"x":Infinity}', b"[]", b"null", b"\xff"]
)
def test_ambiguous_or_nonobject_jsonl_is_refused(body: bytes) -> None:
    with pytest.raises(ValueError):
        jsonl_rows(body)


def test_reference_input_limits_and_duplicate_metadata_keys(tmp_path: Path) -> None:
    path = tmp_path / "input"
    path.write_bytes(b"12345")
    with pytest.raises(ValueError, match="size"):
        read_bounded(path, 4)
    with pytest.raises(ValueError, match="duplicate"):
        strict_json('{"cases":1,"cases":0}')


def test_shipped_reference_set_is_admitted_without_network() -> None:
    meta, rows = load_reference_set(ROOT / "evals/datasets/reference.jsonl")
    assert len(rows) == meta["cases"] > 0
    assert len(meta["content_digest"]) == 64


def test_valid_reference_cli_proves_sources_and_reports_actual_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, out = tmp_path / "reference.jsonl", tmp_path / "report.json"
    meta = freeze_reference(path)
    citation, span = evidence()
    requests: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"status": "answered", "citations": [citation]})
        return httpx.Response(200, json=span)

    monkeypatch.setattr(
        runner,
        "EvaluationHTTP",
        lambda base, token, timeout: EvaluationHTTP(
            base, token, timeout, transport=httpx.MockTransport(serve)
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reference-eval",
            "--set",
            str(path),
            "--out",
            str(out),
            "--base",
            "https://api.example.invalid/api",
            "--token",
            "synthetic-reader",
        ],
    )
    assert runner.main() == 0
    report = json.loads(out.read_text())
    assert report["status"] == "PASS"
    assert report["reference_set_digest"] == meta["content_digest"]
    assert report["retrieval_effectiveness"]["supported_answers"] == 1
    assert len(requests) == 2
    assert json.loads(requests[0].content)["as_of"] == report["default_as_of"]
    assert requests[1].url.params["as_of"] == report["default_as_of"]
    assert all(
        request.headers["Authorization"] == "Bearer synthetic-reader" for request in requests
    )
