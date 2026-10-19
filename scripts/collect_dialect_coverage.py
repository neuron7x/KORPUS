#!/usr/bin/env python3
"""Run a real coverage producer, then bind its native data to the executed source."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from coverage.exceptions import CoverageException
from coverage_execution_contract import (
    DEFAULT_SOURCE,
    ROOT,
    SCHEMA,
    SOURCE_INPUTS,
    CoverageContractError,
    config_text,
    locked_version,
    native_report,
    relative_path,
    require,
    run_identity,
    sha256,
    snapshot,
    write_json,
)


def prepare_outputs(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    paths = [args.data_file, args.report, args.receipt]
    if args.xml_report is not None:
        paths.append(args.xml_report)
    for path in paths:
        relative_path(root, path)
        require(
            path.relative_to(root).parts[0] == "var",
            "INVALID_PATH",
            "coverage outputs must be under var/",
        )
    require(len(set(paths)) == len(paths), "INVALID_PATH", "coverage outputs must be distinct")
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
    # A killed previous pytest-cov invocation can leave parallel shards. They are
    # not evidence for this execution and must never be silently combined into it.
    for shard in args.data_file.parent.glob(args.data_file.name + ".*"):
        require(
            shard.is_file() and not shard.is_symlink(),
            "INVALID_PATH",
            f"invalid coverage shard: {shard}",
        )
        shard.unlink()


def execute(args: argparse.Namespace, sources: list[str]) -> int:
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=args.data_file.parent, suffix=".ini"
    ) as config:
        config.write(config_text(sources))
        config.flush()
        environment = os.environ.copy()
        environment["COVERAGE_FILE"] = str(args.data_file)
        environment["COVERAGE_RCFILE"] = config.name
        require(
            not environment.get("COVERAGE_FORCE_CONFIG"),
            "COVERAGE_CONFIG",
            "COVERAGE_FORCE_CONFIG conflicts with the producer contract",
        )
        result = subprocess.run(args.command, cwd=args.root, env=environment, check=False)
    return result.returncode


def collect(args: argparse.Namespace) -> None:
    prepare_outputs(args)
    root = args.root.resolve()
    sources = args.source or list(DEFAULT_SOURCE)
    inputs = args.source_input or list(SOURCE_INPUTS)
    args.command = args.command[1:] if args.command[:1] == ["--"] else args.command
    require(bool(args.command), "MISSING_COMMAND", "a real command is required after --")
    version = locked_version()
    identity = run_identity()
    for source in sources:
        relative_path(root, root / source)
        require((root / source).is_dir(), "INVALID_SOURCE", f"source directory missing: {source}")
    before = snapshot(root, inputs)
    started = datetime.now(UTC).isoformat()
    returncode = execute(args, sources)
    require(
        returncode == 0,
        "PRODUCER_FAILED",
        f"{args.dialect} coverage command exited {returncode}",
    )
    after = snapshot(root, inputs)
    require(
        before == after,
        "SOURCE_CHANGED_DURING_EXECUTION",
        f"{args.dialect} producer changed source bytes",
    )
    native_report(args.data_file, args.report, root, sources, args.xml_report)
    require(
        before == snapshot(root, inputs),
        "SOURCE_CHANGED_DURING_REPORT",
        "source changed while reporting coverage",
    )
    write_json(
        args.receipt,
        {
            "schema": SCHEMA,
            "status": "PASS",
            "dialect": args.dialect,
            "coverage_version": version,
            "sources": list(sources),
            "coverage_config": config_text(sources),
            "source_before": before,
            "source_after_sha256": after["sha256"],
            "run": identity,
            "execution": {
                "command": args.command,
                "exit_code": returncode,
                "started_at": started,
                "completed_at": datetime.now(UTC).isoformat(),
            },
            "artifacts": {
                "data": {
                    "path": relative_path(root, args.data_file),
                    "sha256": sha256(args.data_file),
                },
                "report": {"path": relative_path(root, args.report), "sha256": sha256(args.report)},
            },
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dialect", choices=("sqlite", "postgresql"), required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source", action="append")
    parser.add_argument("--source-input", action="append")
    parser.add_argument("--data-file", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--xml-report", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = args.root.resolve()
    name = "postgres" if args.dialect == "postgresql" else "sqlite"
    args.data_file = args.data_file or Path(f"var/coverage-{name}.data")
    args.report = args.report or Path(
        "var/coverage-postgres.json" if name == "postgres" else "var/coverage.json"
    )
    args.receipt = args.receipt or Path(f"var/coverage-{name}-receipt.json")
    for attribute in ("data_file", "report", "receipt", "xml_report"):
        path = getattr(args, attribute)
        if path is not None:
            setattr(args, attribute, root / path)
    try:
        collect(args)
    except (CoverageContractError, CoverageException, OSError, ValueError) as error:
        failure = {
            "schema": SCHEMA,
            "status": "FAIL",
            "dialect": args.dialect,
            "error_code": getattr(error, "code", "INVALID_COVERAGE"),
            "reason": str(error),
        }
        # Only write to an already validated output directory. A malformed path is
        # rejected without allowing the error reporter to write outside var/.
        if (
            args.receipt.parent.is_dir()
            and args.receipt.is_relative_to(root / "var")
            and not args.receipt.is_symlink()
        ):
            relative_path(root, args.receipt)
            write_json(args.receipt, failure)
        print(json.dumps(failure, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "dialect": args.dialect,
                "receipt": relative_path(root, args.receipt),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
