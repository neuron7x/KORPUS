"""Semantic closure for the branch debt recorded by issue 54.

These tests exercise refusal edges, not just successful examples: malformed coverage
evidence must stay unmergeable, SBOM subjects must remain byte-bound, and an answer
must never cross its captured corpus snapshot.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, cast

import pytest
from korpus.application import answer_snapshot, coverage_evidence, sbom_evidence
from korpus.application.answer_snapshot import (
    SnapshotAnswerAbort,
    SnapshotAnswerRuntime,
    SnapshotAuditPolicy,
)
from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    CorpusReadToken,
    CorpusSnapshotReader,
)
from korpus.application.ports import Repository
from korpus.application.query_plan import QueryPlan
from korpus.application.risk import QueryRisk
from korpus.domain.models import (
    AccessTier,
    Answer,
    AnswerStatus,
    Identity,
    QueryRequest,
    RetrievedEvidence,
)
from korpus.infrastructure import repository as repository_module
from korpus.infrastructure.repository import SqlRepository, _is_contention
from sqlalchemy.exc import OperationalError

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64


def _coverage_entry() -> dict[str, Any]:
    return {
        "executed_lines": [1, 2],
        "missing_lines": [],
        "excluded_lines": [],
        "executed_branches": [[1, 2], [1, 3]],
        "missing_branches": [],
        "summary": {
            "num_statements": 2,
            "covered_lines": 2,
            "missing_lines": 0,
            "num_branches": 2,
            "covered_branches": 2,
            "missing_branches": 0,
            "num_partial_branches": 0,
        },
    }


def _coverage_report(path: str = "measured.py", dialect: str = "sqlite") -> dict[str, Any]:
    report: dict[str, Any] = {
        "meta": {"format": 3},
        "files": {path: _coverage_entry()},
        "totals": copy.deepcopy(_coverage_entry()["summary"]),
    }
    structure = coverage_evidence.coverage_structure(report)
    assert structure is not None
    report["korpus_coverage"] = {
        "schema": coverage_evidence.RUN_SCHEMA,
        "dialect": dialect,
        "coverage_schema": 3,
        "digest_scope": "tracked_tree",
        "source_tree_sha256": _DIGEST_A,
        "source_inputs_sha256": _DIGEST_B,
        "file_structure_sha256": coverage_evidence.canonical_json_sha256(structure),
    }
    return report


def _coverage_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    return _coverage_report(dialect="sqlite"), _coverage_report(dialect="postgresql")


def _coverage_union() -> dict[str, Any]:
    primary, secondary = _coverage_pair()
    merged: dict[str, Any] = coverage_evidence.merge_reports(
        primary,
        secondary,
        input_sha256={"sqlite": _DIGEST_A, "postgresql": _DIGEST_B},
        receipt_sha256={"sqlite": _DIGEST_B, "postgresql": _DIGEST_A},
        run_identity={"run_id": 54},
    )
    return merged


def test_coverage_structure_refuses_every_ambiguous_shape() -> None:
    assert coverage_evidence.coverage_structure({}) is None
    assert coverage_evidence.coverage_structure({"files": {}}) is None
    assert coverage_evidence.coverage_structure({"files": {"": _coverage_entry()}}) is None

    invalid_count = _coverage_entry()
    invalid_count["summary"]["num_branches"] = True
    assert coverage_evidence.coverage_structure({"files": {"a.py": invalid_count}}) is None


def test_source_input_digest_binds_in_tree_bytes_and_refuses_escape_or_absence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = root / "measured.py"
    source.write_text("first\n", encoding="utf-8")
    report = _coverage_report()

    first = coverage_evidence.source_inputs_sha256(report, root)
    source.write_text("second\n", encoding="utf-8")
    assert coverage_evidence.source_inputs_sha256(report, root) != first

    with pytest.raises(ValueError, match="valid file structure"):
        coverage_evidence.source_inputs_sha256({}, root)

    outside = tmp_path / "outside.py"
    outside.write_text("foreign\n", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes repository"):
        coverage_evidence.source_inputs_sha256(_coverage_report("../outside.py"), root)

    source.unlink()
    with pytest.raises(ValueError, match="input is absent"):
        coverage_evidence.source_inputs_sha256(report, root)


def test_stamping_requires_a_supported_dialect_valid_report_and_real_source(
    tmp_path: Path,
) -> None:
    (tmp_path / "measured.py").write_text("measured = True\n", encoding="utf-8")
    unstamped = _coverage_report()
    unstamped.pop("korpus_coverage")

    with pytest.raises(ValueError, match="unsupported coverage dialect"):
        coverage_evidence.stamp_report(
            unstamped, dialect="oracle", source_tree_sha256=_DIGEST_A, root=tmp_path
        )
    with pytest.raises(ValueError, match="unsupported coverage"):
        coverage_evidence.stamp_report(
            {}, dialect="sqlite", source_tree_sha256=_DIGEST_A, root=tmp_path
        )

    stamped = coverage_evidence.stamp_report(
        unstamped, dialect="sqlite", source_tree_sha256=_DIGEST_A, root=tmp_path
    )
    assert coverage_evidence.coverage_report_problem(stamped) is None
    assert stamped["korpus_coverage"]["source_tree_sha256"] == _DIGEST_A


def test_coverage_report_refuses_invalid_files_totals_and_provenance() -> None:
    report = _coverage_report()

    no_files = copy.deepcopy(report)
    no_files["files"] = {}
    assert (
        coverage_evidence.coverage_report_problem(no_files) == "coverage report has no valid files"
    )

    malformed_entry = copy.deepcopy(report)
    malformed_entry["files"]["measured.py"]["executed_lines"] = [1, 1]
    assert "malformed/duplicated" in str(coverage_evidence.coverage_report_problem(malformed_entry))

    contradictory_totals = copy.deepcopy(report)
    contradictory_totals["totals"]["covered_lines"] = 1
    assert coverage_evidence.coverage_report_problem(contradictory_totals) == (
        "coverage totals do not equal per-file counts"
    )

    report.pop("korpus_coverage")
    assert coverage_evidence.coverage_report_problem(report) == (
        "coverage run provenance is absent or inconsistent"
    )
    assert coverage_evidence.coverage_report_problem(report, require_provenance=False) is None


def test_file_evidence_rejects_duplicate_overlapping_and_impossible_sets() -> None:
    assert coverage_evidence._file_problem(None) == "file entry/summary is not an object"

    malformed = _coverage_entry()
    malformed["executed_lines"] = [1, 1]
    assert coverage_evidence._file_problem(malformed) == (
        "line or branch sets are malformed/duplicated"
    )

    overlapping = _coverage_entry()
    overlapping["missing_lines"] = [1]
    assert coverage_evidence._file_problem(overlapping) == "covered and missing sets overlap"

    impossible = _coverage_entry()
    impossible["missing_branches"] = [[9, 10]]
    impossible["summary"]["missing_branches"] = 1
    assert coverage_evidence._file_problem(impossible) == (
        "branch summary is arithmetically impossible"
    )
    assert coverage_evidence._file_problem(_coverage_entry()) is None


def test_exact_set_parsers_refuse_wrong_types_booleans_and_duplicates() -> None:
    with pytest.raises(ValueError, match="invalid branch arcs"):
        coverage_evidence._arcs(None)
    assert coverage_evidence._arcs_or_none("1,2") is None
    assert coverage_evidence._arcs_or_none([[1]]) is None
    assert coverage_evidence._arcs_or_none([[1, True]]) is None
    assert coverage_evidence._arcs_or_none([[1, 2], [1, 2]]) is None
    assert coverage_evidence._integers("1") is None
    assert coverage_evidence._integers([True]) is None
    assert coverage_evidence._integers([1, 1]) is None
    assert coverage_evidence._integers([1, 2]) == {1, 2}


def test_run_pair_requires_the_same_executable_subject_and_exact_dialects() -> None:
    primary, secondary = _coverage_pair()

    shifted_lines = copy.deepcopy(secondary)
    shifted_lines["files"]["measured.py"]["executed_lines"] = [1, 3]
    shifted_lines["files"]["measured.py"]["missing_lines"] = []
    assert "executable lines" in str(coverage_evidence.same_subject_problem(primary, shifted_lines))

    same_dialect = copy.deepcopy(secondary)
    same_dialect["korpus_coverage"]["dialect"] = "sqlite"
    assert coverage_evidence.same_subject_problem(primary, same_dialect) == (
        "coverage runs do not name the sqlite/postgresql pair"
    )

    foreign_tree = copy.deepcopy(secondary)
    foreign_tree["korpus_coverage"]["source_tree_sha256"] = "c" * 64
    assert "source_tree_sha256" in str(
        coverage_evidence.same_subject_problem(primary, foreign_tree)
    )
    assert coverage_evidence.same_subject_problem(primary, secondary) is None


def test_merge_refuses_a_foreign_subject_and_recomputes_exact_union_sets() -> None:
    primary, secondary = _coverage_pair()
    secondary["korpus_coverage"]["source_inputs_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="source_inputs_sha256"):
        coverage_evidence.merge_reports(
            primary,
            secondary,
            input_sha256={"sqlite": _DIGEST_A, "postgresql": _DIGEST_B},
            receipt_sha256={"sqlite": _DIGEST_B, "postgresql": _DIGEST_A},
            run_identity={},
        )

    union = _coverage_union()
    assert coverage_evidence.coverage_union_problem(union) is None
    assert union["files"]["measured.py"]["summary"]["missing_branches"] == 0


def test_union_refuses_absent_subject_incomplete_maps_and_invalid_digests() -> None:
    union = _coverage_union()

    absent = copy.deepcopy(union)
    absent.pop("dialect_union")
    assert coverage_evidence.coverage_union_problem(absent) == "coverage union provenance is absent"

    inconsistent = copy.deepcopy(union)
    inconsistent["korpus_coverage"]["digest_scope"] = "working_tree"
    assert coverage_evidence.coverage_union_problem(inconsistent) == (
        "coverage union subject is inconsistent"
    )

    incomplete = copy.deepcopy(union)
    incomplete["dialect_union"]["input_sha256"].pop("postgresql")
    assert coverage_evidence.coverage_union_problem(incomplete) == (
        "coverage union input_sha256 is incomplete"
    )

    bad_digest = copy.deepcopy(union)
    bad_digest["dialect_union"]["input_receipt_sha256"]["sqlite"] = "not-a-digest"
    assert coverage_evidence.coverage_union_problem(bad_digest) == (
        "coverage union input_receipt_sha256 contains an invalid digest"
    )


def test_coverage_plan_optionally_binds_the_evidence_source_tree() -> None:
    union = _coverage_union()
    plan = {
        "schema": "korpus.coverage-gap-plan.v3",
        "status": "PASS",
        "coverage_union_sha256": _DIGEST_A,
        "coverage_union_schema": coverage_evidence.UNION_SCHEMA,
        "coverage_source_tree_sha256": _DIGEST_A,
        "coverage_source_inputs_sha256": _DIGEST_B,
        "github_run": {"run_id": 54},
        "source_tree_sha256": _DIGEST_B,
    }
    assert coverage_evidence.coverage_plan_problem(plan, union, _DIGEST_A) is None
    assert (
        coverage_evidence.coverage_plan_problem(
            plan, union, _DIGEST_A, evidence_source_sha256=_DIGEST_A
        )
        == "evidence source"
    )
    plan["source_tree_sha256"] = _DIGEST_A
    assert (
        coverage_evidence.coverage_plan_problem(
            plan, union, _DIGEST_A, evidence_source_sha256=_DIGEST_A
        )
        is None
    )


def _sbom(*components: tuple[str, str]) -> dict[str, Any]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "components": [
            {"type": "library", "name": name, "version": version} for name, version in components
        ],
    }


def test_sbom_component_and_lock_coverage_fail_closed_on_empty_evidence() -> None:
    complete = _sbom(("alpha_package", "1.0"), ("beta", "2.0"))
    assert sbom_evidence.sbom_has_components(complete, {"alpha-package", "beta"}) is True
    assert sbom_evidence.sbom_has_components(complete, set()) is False
    assert sbom_evidence.sbom_has_components({}, {"alpha-package"}) is False
    assert sbom_evidence.source_sbom_covers_lock(complete, {}) is False
    assert sbom_evidence.source_sbom_covers_lock({}, {"alpha-package": "1.0"}) is False
    assert (
        sbom_evidence.source_sbom_covers_lock(complete, {"alpha-package": "1.0", "beta": "2.0"})
        is True
    )


def test_container_subjects_bind_both_image_and_sbom_digests() -> None:
    sboms = {"api-sbom.cdx.json": b"api", "web-sbom.cdx.json": b"web"}
    subjects = {
        "api-image.tar": {
            "sha256": _DIGEST_A,
            "sbom": "api-sbom.cdx.json",
            "sbom_sha256": sbom_evidence.sha256_bytes(b"api"),
        },
        "web-image.tar": {
            "sha256": _DIGEST_B,
            "sbom": "web-sbom.cdx.json",
            "sbom_sha256": sbom_evidence.sha256_bytes(b"web"),
        },
    }
    assert sbom_evidence._container_subjects_bound(None, sboms) is False
    assert sbom_evidence._container_subjects_bound(subjects, sboms) is True

    wrong_sbom = copy.deepcopy(subjects)
    wrong_sbom["web-image.tar"]["sbom_sha256"] = _DIGEST_A
    assert sbom_evidence._container_subjects_bound(wrong_sbom, sboms) is False


def _identity() -> Identity:
    return Identity(
        subject="issue-54-coverage",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )


def _query() -> QueryRequest:
    return QueryRequest(
        text="Контроль знімка корпусу", corpus_ids=["public"], as_of=date(2026, 10, 19)
    )


def _token() -> CorpusReadToken:
    return CorpusReadToken(
        state_epoch=54,
        release_id=_DIGEST_A,
        as_of=date(2026, 10, 19),
        corpus_ids=frozenset({"public"}),
        authorization_scope_id=_DIGEST_B,
    )


def _policy() -> SnapshotAuditPolicy:
    return SnapshotAuditPolicy(
        minimum_score=0.5,
        minimum_query_coverage=0.5,
        minimum_support_score=0.5,
        calibration_id="issue-54",
    )


class _SnapshotReader:
    def __init__(self, *, fail_capture: bool = False, fail_validate: bool = False) -> None:
        self.fail_capture = fail_capture
        self.fail_validate = fail_validate
        self.validations = 0

    def capture(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
    ) -> CorpusReadToken:
        del identity, corpus_ids, as_of
        if self.fail_capture:
            raise CorpusConsistencyError("capture changed")
        return _token()

    def validate(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
    ) -> None:
        del identity, corpus_ids, as_of, token
        self.validations += 1
        if self.fail_validate:
            raise CorpusConsistencyError("validation changed")


@dataclass(frozen=True)
class _Span:
    id: str
    ordinal: int


@dataclass(frozen=True)
class _Hit:
    span: _Span
    score: float
    query_coverage: float


class _SnapshotRetriever:
    def __init__(
        self,
        reader: CorpusSnapshotReader,
        results: Mapping[str, list[_Hit]] | None = None,
        *,
        fail_on: str | None = None,
    ) -> None:
        self.snapshot_reader = reader
        self.results = dict(results or {})
        self.fail_on = fail_on

    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
        limit: int = 8,
    ) -> list[RetrievedEvidence]:
        del identity, corpus_ids, as_of, token, limit
        if text == self.fail_on:
            raise CorpusConsistencyError("search changed")
        return cast(list[RetrievedEvidence], self.results.get(text, []))


def _runtime(
    reader: _SnapshotReader,
    retriever: _SnapshotRetriever | None = None,
) -> SnapshotAnswerRuntime:
    selected = retriever or _SnapshotRetriever(reader)
    return SnapshotAnswerRuntime(
        cast(Repository, object()),
        selected,
        _policy(),
        cast(CorpusSnapshotReader, reader),
    )


def _answer(release: str = _DIGEST_A) -> Answer:
    return Answer(
        status=AnswerStatus.INSUFFICIENT_EVIDENCE,
        text="Контрольна відмова.",
        retrieval_score=0.0,
        evidence_coverage=0.0,
        query_coverage=0.0,
        decision_reason="test_control",
        calibration_id="issue-54",
        corpus_release=release,
    )


def _capture_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def record(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(answer_snapshot, "append_answer_audit", record)
    return calls


def test_capture_failure_abstains_audits_and_aborts_before_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_audits(monkeypatch)
    runtime = _runtime(_SnapshotReader(fail_capture=True))

    with pytest.raises(SnapshotAnswerAbort) as caught:
        runtime.begin(_identity(), _query(), frozenset({"public"}))

    assert caught.value.answer.decision_reason == "corpus_snapshot_unavailable"
    assert caught.value.answer.limitations[-1] == "Snapshot consistency: CorpusConsistencyError."
    assert len(calls) == 1
    assert calls[0][1]["token"] is None


def test_search_plan_deduplicates_by_span_and_keeps_the_strongest_ranked_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_audits(monkeypatch)
    reader = _SnapshotReader()
    retriever = _SnapshotRetriever(
        reader,
        {
            "asked": [_Hit(_Span("a", 2), 0.6, 0.7), _Hit(_Span("b", 1), 0.5, 0.8)],
            "weaker": [_Hit(_Span("a", 2), 0.4, 1.0)],
            "stronger": [_Hit(_Span("a", 2), 0.9, 0.6)],
        },
    )
    session = _runtime(reader, retriever).begin(_identity(), _query(), frozenset({"public"}))

    results = session.search_plan(
        QueryPlan(asked="asked", variants=("weaker", "stronger")), QueryRisk.STANDARD
    )

    assert [(str(item.span.id), item.score) for item in results] == [("a", 0.9), ("b", 0.5)]


def test_search_snapshot_change_discards_results_and_audits_the_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_audits(monkeypatch)
    reader = _SnapshotReader()
    session = _runtime(reader, _SnapshotRetriever(reader, fail_on="asked")).begin(
        _identity(), _query(), frozenset({"public"})
    )

    with pytest.raises(SnapshotAnswerAbort) as caught:
        session.search_plan(QueryPlan(asked="asked"), QueryRisk.STANDARD)

    assert caught.value.answer.decision_reason == "corpus_snapshot_changed"
    assert calls[0][0][4:6] == ([], [])
    assert calls[0][1]["token"] == _token()


def test_finish_keeps_a_matching_validated_answer_and_audits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_audits(monkeypatch)
    reader = _SnapshotReader()
    session = _runtime(reader).begin(_identity(), _query(), frozenset({"public"}))
    answer = _answer()

    assert session.finish(answer, [], [], QueryRisk.STANDARD) is answer
    assert reader.validations == 1
    assert calls[0][0][3] is answer


def test_finish_discards_a_foreign_release_before_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_audits(monkeypatch)
    reader = _SnapshotReader()
    session = _runtime(reader).begin(_identity(), _query(), frozenset({"public"}))
    candidate: list[Any] = [object()]

    result = session.finish(
        _answer(_DIGEST_B),
        candidate,
        candidate,
        QueryRisk.STANDARD,
        composition="foreign",
    )

    assert result.decision_reason == "corpus_release_mismatch"
    assert reader.validations == 1
    assert calls[0][0][4:6] == ([], [])
    assert calls[0][1]["composition"] == "discarded: answer release did not match snapshot token"


def test_finish_discards_work_when_validation_detects_a_changed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_audits(monkeypatch)
    reader = _SnapshotReader(fail_validate=True)
    session = _runtime(reader).begin(_identity(), _query(), frozenset({"public"}))
    candidate: list[Any] = [object()]

    result = session.finish(
        _answer(),
        candidate,
        candidate,
        QueryRisk.STANDARD,
        composition="candidate",
    )

    assert result.decision_reason == "corpus_snapshot_changed"
    assert calls[0][0][4:6] == ([], [])
    assert calls[0][1]["composition"] == "discarded: corpus snapshot changed"


class _SqlStateError(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate
        super().__init__(sqlstate)


def test_contention_is_decided_by_sqlstate_before_driver_message() -> None:
    retryable = OperationalError("UPDATE", {}, _SqlStateError("40001"))
    foreign = OperationalError("UPDATE", {}, _SqlStateError("99999"))
    fallback = OperationalError("UPDATE", {}, Exception("database is locked"))

    assert _is_contention(retryable) is True
    assert _is_contention(foreign) is False
    assert _is_contention(fallback) is True


class _ResetConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


class _ResetTransaction(AbstractContextManager[_ResetConnection]):
    def __init__(self, connection: _ResetConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _ResetConnection:
        return self.connection

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc_type, exc_value, traceback
        return False


class _ResetDialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _ResetEngine:
    def __init__(self, dialect: str) -> None:
        self.dialect = _ResetDialect(dialect)
        self.connection = _ResetConnection()

    def begin(self) -> _ResetTransaction:
        return _ResetTransaction(self.connection)


class _ResetAnchor:
    def __init__(self) -> None:
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1


@pytest.mark.parametrize("dialect, drops_fts", [("sqlite", True), ("postgresql", False)])
def test_repository_reset_drops_fts_only_for_sqlite(
    monkeypatch: pytest.MonkeyPatch, dialect: str, drops_fts: bool
) -> None:
    engine = _ResetEngine(dialect)
    anchor = _ResetAnchor()
    initialized: list[bool] = []
    dropped: list[object] = []
    repository = object.__new__(SqlRepository)
    mutable = cast(Any, repository)
    mutable.engine = engine
    mutable.anchor_store = anchor
    mutable.initialize = lambda: initialized.append(True)

    def record_drop(value: object) -> None:
        dropped.append(value)

    monkeypatch.setattr(repository_module.metadata, "drop_all", record_drop)

    repository.reset()

    assert bool(engine.connection.statements) is drops_fts
    assert all("evidence_fts" in statement for statement in engine.connection.statements)
    assert dropped == [engine]
    assert anchor.resets == 1
    assert initialized == [True]
