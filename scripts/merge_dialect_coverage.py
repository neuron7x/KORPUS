#!/usr/bin/env python3
"""Verify both dialect executions and combine their native coverage datasets.

The legacy JSON paths remain the public CLI. Each now requires its corresponding
raw dataset and successful execution receipt; JSON counts alone cannot establish
that two measurements describe the same executable lines and branch arcs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from coverage.exceptions import CoverageException
from coverage_execution_contract import ROOT, CoverageContractError, relative_path, require
from coverage_union import combine
from coverage_union import same_subject as same_subject

DEFAULT_PATHS = {
    "primary": "var/coverage.json",
    "secondary": "var/coverage-postgres.json",
    "primary_data": "var/coverage-sqlite.data",
    "secondary_data": "var/coverage-postgres.data",
    "primary_receipt": "var/coverage-sqlite-receipt.json",
    "secondary_receipt": "var/coverage-postgres-receipt.json",
    "out": "var/coverage-union.json",
}


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source", action="append")
    parser.add_argument("--source-input", action="append")
    for name, path in DEFAULT_PATHS.items():
        parser.add_argument("--" + name.replace("_", "-"), type=Path, default=Path(path))
    args = parser.parse_args()
    for name in DEFAULT_PATHS:
        setattr(args, name, args.root.resolve() / getattr(args, name))
    return args


def prepare_outputs(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    for name in DEFAULT_PATHS:
        relative_path(root, getattr(args, name))
    outputs = (args.out, args.out.with_suffix(".data"))
    inputs = [getattr(args, name) for name in DEFAULT_PATHS if name != "out"]
    require(
        args.out.is_relative_to(root / "var"), "INVALID_PATH", "coverage output must be under var/"
    )
    require(
        len(set(inputs + list(outputs))) == 8, "INVALID_PATH", "coverage paths must all be distinct"
    )
    for output in outputs:
        relative_path(root, output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.unlink(missing_ok=True)


def main() -> int:
    args = arguments()
    try:
        prepare_outputs(args)
        merged = combine(args)
    except (CoverageContractError, CoverageException, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_code": getattr(error, "code", "INVALID_COVERAGE"),
                    "reason": str(error),
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "out": relative_path(args.root.resolve(), args.out),
                "missing_branches": merged["totals"]["missing_branches"],
                "totals": merged["totals"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
