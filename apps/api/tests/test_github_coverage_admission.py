"""Hosted coverage requires authenticated subjects and independently regenerated native data."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import coverage_union  # noqa: E402
import github_coverage_admission as admission  # noqa: E402
from coverage_execution_contract import DEFAULT_SOURCE, native_report  # noqa: E402
from coverage_union import combine_native, union_metadata  # noqa: E402
from github_coverage_admission import verified_coverage  # noqa: E402
from github_evidence_artifact import admit_artifact, artifact_inventory, digest  # noqa: E402
from github_evidence_run import POSTGRES, SQLITE, admit_run  # noqa: E402

from .hosted_evidence_fixtures import (  # noqa: E402
    SELECTED,
    EvidenceFixture,
    encoded,
    measured_fixture,
)


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> EvidenceFixture:
    return measured_fixture(tmp_path_factory.mktemp("hosted-native"))


def _admit(fixture: EvidenceFixture):
    run = admit_run(fixture.api, SELECTED, fixture.checkout)
    inventory = artifact_inventory(fixture.api, run)
    first = admit_artifact(fixture.api, run, SQLITE, inventory)
    second = admit_artifact(fixture.api, run, POSTGRES, inventory)
    return verified_coverage(run, first, second)


def test_real_two_dialect_data_reconstructs_full_native_union(measured: EvidenceFixture) -> None:
    fixture = measured.clone()
    result = _admit(fixture)
    assert result["totals"]["percent_covered"] == 100
    assert result["totals"]["covered_branches"] == 2
    assert result["dialect_union"]["runs"] == ["sqlite", "postgresql"]
    assert fixture.api.downloads.count("/actions/artifacts/201/zip") == 1
    assert fixture.api.downloads.count("/actions/artifacts/202/zip") == 1


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("dialect", "sqlite", "must measure postgresql"),
        ("status", "FAIL", "successful coverage execution"),
        ("coverage_version", "0.0.0", "version differs"),
        ("source_after_sha256", "d" * 64, "different source bytes"),
    ],
)
def test_coherent_outer_archive_cannot_forge_native_receipt(
    measured: EvidenceFixture, field: str, value, message: str
) -> None:
    fixture = measured.clone()
    name = "coverage-postgres-receipt.json"
    receipt = json.loads(fixture.members[POSTGRES.job][name])
    receipt[field] = value
    fixture.members[POSTGRES.job][name] = encoded(receipt)
    fixture.members[SQLITE.job][name] = encoded(receipt)
    fixture.repack(POSTGRES)
    fixture.repack(SQLITE)
    with pytest.raises(ValueError, match=message):
        _admit(fixture)


@pytest.mark.parametrize(
    "field", ["GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"]
)
def test_inner_execution_cannot_borrow_another_run(measured: EvidenceFixture, field: str) -> None:
    fixture = measured.clone()
    name = "coverage-sqlite-receipt.json"
    receipt = json.loads(fixture.members[SQLITE.job][name])
    receipt["run"][field] = "foreign"
    fixture.members[SQLITE.job][name] = encoded(receipt)
    fixture.sync_union_receipts()
    fixture.repack(SQLITE)
    with pytest.raises(ValueError, match="another repository/SHA/run/attempt"):
        _admit(fixture)


def test_forged_secondary_copy_in_publisher_artifact_is_refused(measured: EvidenceFixture) -> None:
    fixture = measured.clone()
    fixture.members[SQLITE.job]["coverage-postgres-receipt.json"] = b'{"status":"PASS"}'
    fixture.repack(SQLITE)
    with pytest.raises(ValueError, match="secondary coverage copy conflicts"):
        _admit(fixture)


def test_native_data_refutes_report_with_coherent_receipt_and_zip_hashes(
    measured: EvidenceFixture,
) -> None:
    fixture = measured.clone()
    report = json.loads(fixture.members[SQLITE.job]["coverage.json"])
    report["totals"]["covered_branches"] = 2
    payload = encoded(report)
    receipt = json.loads(fixture.members[SQLITE.job]["coverage-sqlite-receipt.json"])
    receipt["artifacts"]["report"]["sha256"] = digest(payload)
    fixture.members[SQLITE.job]["coverage.json"] = payload
    fixture.members[SQLITE.job]["coverage-sqlite-receipt.json"] = encoded(receipt)
    fixture.sync_union_receipts()
    fixture.repack(SQLITE)
    with pytest.raises(ValueError, match="native dataset and actual source universe"):
        _admit(fixture)


@pytest.mark.parametrize(
    "name", ["coverage.json", "coverage-sqlite-receipt.json", "coverage-union.json"]
)
def test_duplicate_member_json_keys_are_never_admitted(
    measured: EvidenceFixture, name: str
) -> None:
    fixture = measured.clone()
    fixture.members[SQLITE.job][name] = b'{"status":"FAIL","status":"PASS"}'
    if name == "coverage.json":
        receipt = json.loads(fixture.members[SQLITE.job]["coverage-sqlite-receipt.json"])
        receipt["artifacts"]["report"]["sha256"] = digest(fixture.members[SQLITE.job][name])
        fixture.members[SQLITE.job]["coverage-sqlite-receipt.json"] = encoded(receipt)
    fixture.repack(SQLITE)
    with pytest.raises(ValueError, match="duplicate key"):
        _admit(fixture)


def test_conflicting_publisher_union_is_not_used_as_totals(measured: EvidenceFixture) -> None:
    fixture = measured.clone()
    report = json.loads(fixture.members[SQLITE.job]["coverage-union.json"])
    report["totals"]["covered_lines"] = 1000
    fixture.members[SQLITE.job]["coverage-union.json"] = encoded(report)
    fixture.repack(SQLITE)
    with pytest.raises(ValueError, match="union conflicts"):
        _admit(fixture)


def test_native_receipt_source_membership_is_not_a_candidate_control(
    measured: EvidenceFixture,
) -> None:
    fixture = measured.clone()
    name = "coverage-sqlite-receipt.json"
    record = json.loads(fixture.members[SQLITE.job][name])
    record["source_before"]["files"].pop("apps/api/src/korpus/toy.py")
    fixture.members[SQLITE.job][name] = encoded(record)
    fixture.repack(SQLITE)
    with pytest.raises(ValueError, match="different source bytes"):
        _admit(fixture)


def test_restored_caller_source_swap_cannot_supply_a_false_native_universe(
    measured: EvidenceFixture,
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixture = measured.clone()
    source = fixture.checkout.root / "apps/api/src/korpus/toy.py"
    original = source.read_bytes()
    swapped = original + b"\ndef extra():\n    return 1\n"
    source.write_bytes(swapped)
    try:
        for dialect, producer, prefix, report_name in (
            ("sqlite", SQLITE, "sqlite", "coverage.json"),
            ("postgresql", POSTGRES, "postgres", "coverage-postgres.json"),
        ):
            data = tmp_path / f"{dialect}.data"
            data.write_bytes(fixture.members[producer.job][f"coverage-{prefix}.data"])
            false_report = native_report(
                data, tmp_path / f"{dialect}.json", fixture.checkout.root, DEFAULT_SOURCE
            )
            fixture.members[producer.job][report_name] = encoded(false_report)
            receipt_name = f"coverage-{prefix}-receipt.json"
            receipt = json.loads(fixture.members[producer.job][receipt_name])
            receipt["artifacts"]["report"]["sha256"] = digest(encoded(false_report))
            fixture.members[producer.job][receipt_name] = encoded(receipt)
            (tmp_path / f"{dialect}-receipt.json").write_bytes(encoded(receipt))
        false_union = combine_native(fixture.checkout.root, list(DEFAULT_SOURCE), tmp_path)
        false_union["dialect_union"] = union_metadata(fixture.checkout.source, tmp_path)
        fixture.members[SQLITE.job]["coverage-union.json"] = encoded(false_union)
        for name in POSTGRES.required_members:
            fixture.members[SQLITE.job][name] = fixture.members[POSTGRES.job][name]
        fixture.repack(SQLITE)
        fixture.repack(POSTGRES)
    finally:
        source.write_bytes(original)

    def swap_during_native_read(data, report, root, sources, xml_report=None):
        if root != fixture.checkout.root:
            return native_report(data, report, root, sources, xml_report)
        source.write_bytes(swapped)
        try:
            return native_report(data, report, root, sources, xml_report)
        finally:
            source.write_bytes(original)

    monkeypatch.setattr(admission, "native_report", swap_during_native_read)
    monkeypatch.setattr(coverage_union, "native_report", swap_during_native_read)
    assert (
        false_union["totals"]["num_statements"]
        > json.loads(measured.members[SQLITE.job]["coverage-union.json"])["totals"][
            "num_statements"
        ]
    )
    with pytest.raises(ValueError, match="native dataset and actual source universe"):
        _admit(fixture)
    assert source.read_bytes() == original
