"""A reference result cannot outlive or misidentify the input it actually executed."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

from .evaluation_fixtures import OTHER, VERSION, case, evidence, freeze_reference, sha

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import remap_reference_versions as remapper  # noqa: E402
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


def _version_database(path: Path, versions: dict[str, str]) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE document_versions (id TEXT, source_hash TEXT)")
        connection.executemany("INSERT INTO document_versions VALUES (?, ?)", versions.items())


def _remap_arguments(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "remap-reference",
            "--source-sqlite",
            str(path / "source.db"),
            "--target-url",
            f"sqlite:///{path / 'target.db'}",
            "--reference",
            str(path / "reference.jsonl"),
            "--out",
            str(path / "remapped.jsonl"),
        ],
    )


@pytest.mark.parametrize("alias", [False, True])
def test_remapped_reference_rebinds_sampled_holder_and_preserves_source_provenance(
    alias: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = case()
    row["must_cite_one_of_if_answered"] = [VERSION, OTHER]
    original = tmp_path / "reference.jsonl"
    source_meta = freeze_reference(original, [row])
    source_bytes = original.read_bytes()
    source_hash = sha("synthetic archive bytes")
    other_hash = source_hash if alias else sha("other archive bytes")
    target_id = "00000000-0000-4000-8000-000000000005"
    _version_database(tmp_path / "source.db", {VERSION: source_hash, OTHER: other_hash})
    _version_database(tmp_path / "target.db", {target_id: source_hash})
    _remap_arguments(tmp_path, monkeypatch)

    assert remapper.main() == 0
    metadata, rows = load_reference_set(tmp_path / "remapped.jsonl")
    assert rows == [
        {**row, "sampled_from_version": target_id, "must_cite_one_of_if_answered": [target_id]}
    ]
    assert metadata["content_digest"] != source_meta["content_digest"]
    assert metadata["remapped_from_digest"] == source_meta["content_digest"]
    assert metadata["remapped_from"] == str(original)
    assert metadata["dropped_case_ids"] == []
    assert original.read_bytes() == source_bytes


@pytest.mark.parametrize("missing", ["source", "target"])
def test_remap_drops_missing_sample_instead_of_borrowing_another_holder(
    missing: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = case()
    row["must_cite_one_of_if_answered"] = [VERSION, OTHER]
    refusal = {
        "id": "unrelated-archive",
        "kind": "refusal",
        "stratum": "archive",
        "query": "Which absent label?",
        "expect": "abstained",
    }
    freeze_reference(tmp_path / "reference.jsonl", [row, refusal])
    source = {OTHER: sha("other archive bytes")}
    if missing == "target":
        source[VERSION] = sha("sampled archive bytes")
    _version_database(tmp_path / "source.db", source)
    _version_database(tmp_path / "target.db", {OTHER: sha("other archive bytes")})
    _remap_arguments(tmp_path, monkeypatch)

    assert remapper.main() == 0
    metadata, rows = load_reference_set(tmp_path / "remapped.jsonl")
    assert rows == [refusal]
    assert metadata["dropped_case_ids"] == [row["id"]]
    assert metadata["cases"] == 1


def test_remap_admits_frozen_source_before_database_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "reference.jsonl"
    freeze_reference(path)
    changed = case()
    changed["query"] = "Which different archive label?"
    path.write_text(json.dumps(changed) + "\n")
    _remap_arguments(tmp_path, monkeypatch)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("remapper accessed a database before validating its source set")

    monkeypatch.setattr(remapper, "sqlite_map", forbidden)
    monkeypatch.setattr(remapper, "target_map", forbidden)
    with pytest.raises(ValueError, match="digest"):
        remapper.main()
    assert not (tmp_path / "remapped.jsonl").exists()
