"""A PASS snapshot is complete only when its canonical evidence set is exact."""
from __future__ import annotations

import pytest
from scripts.assurance_snapshot_contract import (
    SNAPSHOT_SCHEMA,
    canonical_snapshot_paths,
    canonical_snapshot_records,
)

RELEASE = "v0.1.1"


def _record(path: str) -> dict[str, object]:
    return {"path": path, "bytes": 1, "sha256": "0" * 64}


def _snapshot(paths: list[str] | None = None) -> dict[str, object]:
    selected = list(canonical_snapshot_paths()) if paths is None else paths
    return {
        "schema": SNAPSHOT_SCHEMA,
        "release": RELEASE,
        "status": "PASS",
        "records": [_record(path) for path in selected],
    }


def test_exact_canonical_snapshot_is_normalized_in_contract_order() -> None:
    failures, records = canonical_snapshot_records(_snapshot(), RELEASE)
    assert failures == ()
    assert tuple(record["path"] for record in records) == canonical_snapshot_paths()


def test_empty_snapshot_cannot_pass_as_complete() -> None:
    failures, records = canonical_snapshot_records(_snapshot([]), RELEASE)
    assert records == ()
    assert any("missing canonical records" in failure for failure in failures)


def test_one_missing_canonical_record_is_rejected() -> None:
    paths = list(canonical_snapshot_paths())[:-1]
    failures, records = canonical_snapshot_records(_snapshot(paths), RELEASE)
    assert records == ()
    assert any("missing canonical records" in failure for failure in failures)


def test_duplicate_canonical_record_is_rejected() -> None:
    paths = list(canonical_snapshot_paths())
    paths.append(paths[0])
    failures, records = canonical_snapshot_records(_snapshot(paths), RELEASE)
    assert records == ()
    assert any("duplicate record" in failure for failure in failures)


@pytest.mark.parametrize(
    "path",
    ["../outside.json", "/tmp/outside.json", "reports/UNDECLARED.json"],
)
def test_noncanonical_paths_are_rejected_without_returning_filesystem_targets(path: str) -> None:
    paths = [*canonical_snapshot_paths(), path]
    failures, records = canonical_snapshot_records(_snapshot(paths), RELEASE)
    assert records == ()
    assert any("non-canonical records" in failure for failure in failures)


def test_wrong_schema_is_rejected() -> None:
    snapshot = _snapshot()
    snapshot["schema"] = "korpus.assurance-snapshot.v0"
    failures, records = canonical_snapshot_records(snapshot, RELEASE)
    assert records == ()
    assert "assurance snapshot schema mismatch" in failures


@pytest.mark.parametrize(
    ("field", "value"),
    [("status", "FAIL"), ("release", "v0.0.0")],
)
def test_wrong_release_or_status_is_rejected(field: str, value: str) -> None:
    snapshot = _snapshot()
    snapshot[field] = value
    failures, records = canonical_snapshot_records(snapshot, RELEASE)
    assert records == ()
    assert "assurance snapshot release/status mismatch" in failures


def test_malformed_record_is_rejected_without_normalization() -> None:
    snapshot = _snapshot()
    records = snapshot["records"]
    assert isinstance(records, list)
    records[0] = {"bytes": 1, "sha256": "0" * 64}
    failures, normalized = canonical_snapshot_records(snapshot, RELEASE)
    assert normalized == ()
    assert any("malformed record" in failure for failure in failures)
