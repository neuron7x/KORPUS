"""The producer binds the report to the snapshot actually executed before HTTP."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

from .evaluation_fixtures import freeze_boundary, sha

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import run_boundary_eval as runner  # noqa: E402
from boundary_eval_set import load_boundary_set  # noqa: E402
from evaluation_http import EvaluationHTTP  # noqa: E402


def test_boundary_producer_binds_pre_network_snapshot_even_if_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "boundary.jsonl"
    meta = freeze_boundary(path)
    original = path.read_bytes()
    seen: list[dict] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.url.host == "api.example.invalid"
        assert request.headers["Authorization"] == "Bearer synthetic-reader"
        if len(seen) == 1:
            path.write_text("different file after the first request\n")
            path.with_suffix(".meta.json").write_text("{}")
        status = "answered" if len(seen) == 1 else "insufficient_evidence"
        return httpx.Response(200, json={"status": status})

    monkeypatch.setattr(
        runner,
        "EvaluationHTTP",
        lambda base, token, timeout: EvaluationHTTP(
            base, token, timeout, transport=httpx.MockTransport(serve)
        ),
    )
    report = runner.evaluate(path, "https://api.example.invalid/api", "synthetic-reader", 1)
    assert report["status"] == "MEASURED"
    assert report["set_digest"] == sha(original.decode()) == meta["digest"]
    assert report["in_corpus"] == {"answered": 1, "judged": 1, "rate": 1}
    assert report["out_of_corpus"] == {"answered": 0, "judged": 1, "rate": 0}
    assert [row["text"] for row in seen] == [
        row["query"] for row in map(json.loads, original.splitlines())
    ]
    assert {row["as_of"] for row in seen} == {report["as_of"]}
    assert report["cannot_judge"] == meta["cannot_judge"]


@pytest.mark.parametrize(
    "poison",
    [
        "changed-query",
        "empty",
        "duplicate-id",
        "unknown-field",
        "unknown-stratum",
        "wrong-expect",
        "missing-query",
        "wrong-count",
        "empty-stratum",
        "wrong-schema",
        "short-digest",
        "missing-limits",
    ],
)
def test_invalid_boundary_set_never_contacts_api(
    poison: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "boundary.jsonl"
    meta = freeze_boundary(path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if poison == "changed-query":
        rows[0]["query"] = "A changed synthetic archive question"
    elif poison == "empty":
        rows = []
    elif poison == "duplicate-id":
        rows[1]["id"] = rows[0]["id"]
    elif poison == "unknown-field":
        rows[0]["trusted"] = True
    elif poison == "unknown-stratum":
        rows[0]["stratum"] = "invented"
    elif poison == "wrong-expect":
        rows[0]["expect"] = "withhold"
    elif poison == "missing-query":
        rows[0]["query"] = " "
    elif poison == "wrong-count":
        meta["cases"] = True
    elif poison == "empty-stratum":
        meta["in_corpus"] = 0
    elif poison == "wrong-schema":
        meta["schema"] = "invented"
    elif poison == "short-digest":
        meta["digest"] = meta["digest"][:16]
    elif poison == "missing-limits":
        meta["cannot_judge"] = []
    body = "".join(json.dumps(row) + "\n" for row in rows)
    if poison not in {"changed-query", "short-digest"}:
        meta["digest"] = sha(body)
    path.write_text(body)
    path.with_suffix(".meta.json").write_text(json.dumps(meta))

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("boundary HTTP preceded set admission")

    monkeypatch.setattr(runner, "EvaluationHTTP", forbidden)
    with pytest.raises(ValueError):
        runner.evaluate(path, "https://api.example.invalid", "synthetic-reader", 1)


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (200, {"status": "invented"}, "FAIL"),
        (200, {"status": {}}, "FAIL"),
        (404, {}, "FAIL"),
        (503, {}, "UNKNOWN"),
        (429, {}, "UNKNOWN"),
    ],
)
def test_boundary_invalid_responses_are_not_withheld_successes(
    status: int, body: dict, expected: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "boundary.jsonl"
    freeze_boundary(path)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        runner,
        "EvaluationHTTP",
        lambda base, token, timeout: EvaluationHTTP(
            base,
            token,
            timeout,
            transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body)),
        ),
    )
    report = runner.evaluate(path, "https://api.example.invalid", "", 1)
    assert report["status"] == expected
    assert report["in_corpus"]["judged"] == report["out_of_corpus"]["judged"] == 0
    assert report["in_corpus"]["rate"] is report["out_of_corpus"]["rate"] is None


def test_shipped_boundary_metadata_matches_actual_historical_bytes() -> None:
    meta, rows = load_boundary_set(ROOT / "evals/datasets/domain_boundary.jsonl")
    assert len(rows) == meta["cases"] == 40
    assert meta["in_corpus"] == meta["out_of_corpus"] == 20
