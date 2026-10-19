"""Admission and native combination of the two required coverage executions."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from coverage_execution_contract import (
    DEFAULT_SOURCE,
    SOURCE_INPUTS,
    CoverageContractError,
    coverage_instance,
    in_directory,
    load_json,
    native_report,
    report_universe,
    require,
    semantic_report,
    sha256,
    snapshot,
    verify_receipt,
    write_json,
)


def same_subject(primary: dict[str, Any], secondary: dict[str, Any]) -> str | None:
    """Compare exact executable line/exclusion/arc universes, never just counts."""
    try:
        left, right = report_universe(primary), report_universe(secondary)
    except CoverageContractError as error:
        return str(error)
    if set(left) != set(right):
        return "different measured source file sets"
    for path in sorted(left):
        if left[path][0] != right[path][0]:
            return f"different executable line universe (тверджень): {path}"
        if left[path][1] != right[path][1]:
            return f"different excluded line universe: {path}"
        if left[path][2] != right[path][2]:
            return f"different branch arc universe: {path}"
    return None


def verified_report(
    dialect: str,
    data: Path,
    report: Path,
    receipt: Path,
    root: Path,
    sources: list[str],
    source: dict[str, Any],
    temporary: Path,
) -> dict[str, Any]:
    # Work on private copies so the data actually combined cannot be replaced
    # after admission. Checksums still refer to the producer's declared paths.
    saved_receipt = temporary / f"{dialect}-receipt.json"
    saved_data = temporary / f"{dialect}.data"
    sha256(receipt)
    shutil.copyfile(receipt, saved_receipt)
    record = load_json(saved_receipt)
    verify_receipt(record, dialect, data, report, source, root, sources)
    shutil.copyfile(data, saved_data)
    require(
        sha256(saved_data) == record["artifacts"]["data"]["sha256"],
        "ARTIFACT_MISMATCH",
        f"{dialect} data changed during admission",
    )
    saved = load_json(report)
    regenerated = native_report(saved_data, temporary / f"{dialect}.json", root, sources)
    require(
        semantic_report(saved) == semantic_report(regenerated),
        "RAW_REPORT_MISMATCH",
        f"{dialect} JSON does not describe its native raw dataset and current source",
    )
    return saved


def combine_native(root: Path, sources: list[str], temporary: Path) -> dict[str, Any]:
    raw = temporary / "combined.data"
    with in_directory(root):
        measured = coverage_instance(raw, sources)
        measured.combine(
            data_paths=[str(temporary / "sqlite.data"), str(temporary / "postgresql.data")],
            strict=True,
            keep=True,
        )
        measured.save()
    return native_report(raw, temporary / "combined.json", root, sources)


def union_metadata(source: dict[str, Any], temporary: Path) -> dict[str, Any]:
    return {
        "schema": "korpus.dialect-coverage-union.v1",
        "runs": ["sqlite", "postgresql"],
        "combiner": "coverage.py native combine and json_report",
        "source_sha256": source["sha256"],
        "source_scope": source["scope"],
        "input_data_sha256": {
            dialect: sha256(temporary / f"{dialect}.data") for dialect in ("sqlite", "postgresql")
        },
        "input_receipt_sha256": {
            dialect: sha256(temporary / f"{dialect}-receipt.json")
            for dialect in ("sqlite", "postgresql")
        },
    }


def combine(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    sources = args.source or list(DEFAULT_SOURCE)
    inputs = args.source_input or list(SOURCE_INPUTS)
    before = snapshot(root, inputs)
    with TemporaryDirectory(dir=args.out.parent, prefix="coverage-combine-") as directory:
        temporary = Path(directory)
        primary = verified_report(
            "sqlite",
            args.primary_data,
            args.primary,
            args.primary_receipt,
            root,
            sources,
            before,
            temporary,
        )
        secondary = verified_report(
            "postgresql",
            args.secondary_data,
            args.secondary,
            args.secondary_receipt,
            root,
            sources,
            before,
            temporary,
        )
        divergence = same_subject(primary, secondary)
        require(divergence is None, "COVERAGE_UNIVERSE_MISMATCH", divergence or "")
        merged = combine_native(root, sources, temporary)
        require(
            before == snapshot(root, inputs),
            "SOURCE_CHANGED_DURING_MERGE",
            "source changed while combining coverage",
        )
        merged["dialect_union"] = union_metadata(before, temporary)
        (temporary / "combined.data").replace(args.out.with_suffix(".data"))
        write_json(args.out, merged)
    return merged
