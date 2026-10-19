"""Shared, fail-closed contract for the two measured coverage executions.

Receipts bind a successful command to immutable source bytes, native coverage data,
and (on Actions) one repository/SHA/run/attempt. They are execution evidence inside
the CI trust boundary, not an independent attestation of a database deployment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import coverage

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "korpus.dialect-coverage-execution.v1"
DEFAULT_SOURCE = ("apps/api/src/korpus",)
# Include tests, locks, producer code and workflow definitions, not just measured
# Python modules. Generated evidence and dependency caches are not source inputs.
SOURCE_INPUTS = (
    "apps/api",
    "apps/web",
    "packages",
    "contracts",
    "scripts",
    "config",
    "evals",
    "deploy",
    "infra",
    ".github/workflows",
    ".gitlab-ci.yml",
    "Makefile",
    "docker-compose.yml",
    ".dockerignore",
    "pytest.ini",
)
EXCLUDED_DIRECTORIES = {
    ".git",
    "__pycache__",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "var",
    "node_modules",
    "dist",
    ".terraform",
}
RUN_FIELDS = ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")
GITLAB_FIELDS = ("CI_PROJECT_PATH", "CI_COMMIT_SHA", "CI_PIPELINE_ID")


class CoverageContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise CoverageContractError(code, message)


def sha256(path: Path) -> str:
    require(path.is_file(), "MISSING_INPUT", f"required coverage input is missing: {path}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), "MISSING_INPUT", f"required coverage input is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "INVALID_JSON", f"expected JSON object: {path}")
    return dict(value)


def object_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CoverageContractError("INVALID_REPORT", f"{name} must be an object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
        temporary = Path(out.name)
        out.write(json.dumps(value, sort_keys=True, indent=2) + "\n")
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def relative_path(root: Path, path: Path) -> str:
    require(path.is_relative_to(root), "INVALID_PATH", f"path is outside source root: {path}")
    require(not path.is_symlink(), "INVALID_PATH", f"symlink is not a coverage input: {path}")
    relative = path.relative_to(root)
    require(".." not in relative.parts, "INVALID_PATH", f"path traverses source root: {path}")
    for parent in path.parents:
        if parent == root:
            break
        require(not parent.is_symlink(), "INVALID_PATH", f"symlink parent: {parent}")
    return relative.as_posix()


def source_files(path: Path) -> Iterator[Path]:
    require(path.exists(), "MISSING_SOURCE", f"declared source input is missing: {path}")
    require(not path.is_symlink(), "INVALID_PATH", f"source symlink: {path}")
    if path.is_file():
        yield path
        return
    for directory, subdirs, files in os.walk(path):
        subdirs[:] = sorted(name for name in subdirs if name not in EXCLUDED_DIRECTORIES)
        for name in subdirs:
            require(
                not (Path(directory) / name).is_symlink(),
                "INVALID_PATH",
                f"source symlink: {Path(directory) / name}",
            )
        for name in sorted(files):
            if not name.endswith((".pyc", ".pyo")):
                yield Path(directory) / name


def snapshot(root: Path, inputs: Sequence[str]) -> dict[str, Any]:
    files: dict[str, str] = {}
    for name in sorted(set(inputs)):
        relative_path(root, root / name)
        for path in source_files(root / name):
            files[relative_path(root, path)] = sha256(path)
    require(bool(files), "EMPTY_SOURCE", "source snapshot contains no files")
    return {
        "scope": "coverage-source-inputs-v1",
        "inputs": sorted(set(inputs)),
        "files": files,
        "sha256": hashlib.sha256(canonical_bytes(files)).hexdigest(),
    }


def locked_version() -> str:
    lock = (ROOT / "apps/api/requirements.dev.lock").read_text(encoding="utf-8")
    versions: list[str] = re.findall(r"^coverage==([^\s\\]+)", lock, re.MULTILINE)
    require(len(versions) == 1, "COVERAGE_LOCK", "expected one locked coverage.py version")
    require(
        coverage.__version__ == versions[0],
        "COVERAGE_VERSION",
        f"coverage.py {coverage.__version__} differs from locked {versions[0]}",
    )
    return versions[0]


def hosted_identity(fields: Sequence[str], kind: str) -> dict[str, str]:
    values = {name: os.environ.get(name, "") for name in fields}
    require(all(values.values()), "RUN_IDENTITY", "hosted coverage requires " + ", ".join(fields))
    require(
        bool(re.fullmatch(r"[^/\s]+(?:/[^/\s]+)+", values[fields[0]]))
        and bool(re.fullmatch(r"[0-9a-f]{40}", values[fields[1]]))
        and all(re.fullmatch(r"[1-9][0-9]*", values[name]) for name in fields[2:]),
        "RUN_IDENTITY",
        "invalid hosted repository/SHA/run/attempt identity",
    )
    return {"kind": kind, **values}


def run_identity() -> dict[str, str]:
    github = os.environ.get("GITHUB_ACTIONS") == "true"
    gitlab = os.environ.get("GITLAB_CI") == "true"
    require(not (github and gitlab), "RUN_IDENTITY", "conflicting hosted CI providers")
    if github:
        return hosted_identity(RUN_FIELDS, "github-actions")
    if gitlab:
        return hosted_identity(GITLAB_FIELDS, "gitlab-ci")
    require(
        not any(os.environ.get(name) for name in (*RUN_FIELDS, *GITLAB_FIELDS)),
        "RUN_IDENTITY",
        "partial hosted identity cannot be treated as a local execution",
    )
    return {"kind": "local"}


def config_text(sources: Sequence[str]) -> str:
    require(
        bool(sources) and all("\n" not in item and "\r" not in item for item in sources),
        "INVALID_SOURCE",
        "coverage requires explicit source directories",
    )
    return (
        "[run]\nbranch = true\nrelative_files = true\nsource =\n"
        + "".join(f"    {source}\n" for source in sources)
        + "[report]\nshow_missing = true\n"
    )


@contextmanager
def in_directory(root: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(previous)


def coverage_instance(data_file: Path, sources: Sequence[str]) -> coverage.Coverage:
    result = coverage.Coverage(
        data_file=str(data_file), config_file=False, branch=True, source=sources
    )
    result.set_option("run:relative_files", True)
    return result


def validate_data(data_file: Path, root: Path, sources: Sequence[str]) -> None:
    sha256(data_file)
    data = coverage.CoverageData(basename=str(data_file))
    data.read()
    require(
        data.has_arcs(), "BRANCH_DATA_REQUIRED", f"raw branch coverage is required: {data_file}"
    )
    files = data.measured_files()
    require(bool(files), "EMPTY_COVERAGE", f"raw coverage contains no measured files: {data_file}")
    for name in files:
        path = Path(name)
        require(
            not path.is_absolute()
            and ".." not in path.parts
            and any(path.is_relative_to(source) for source in sources),
            "RAW_SOURCE_PATH",
            f"raw dataset contains a nonportable or out-of-scope path: {name}",
        )
        relative_path(root, root / path)
        require((root / path).is_file(), "MISSING_SOURCE", f"measured source is missing: {name}")
        require(
            not data.file_tracer(name), "FILE_TRACER", f"unsupported coverage file tracer: {name}"
        )
    require(
        any(data.lines(name) for name in files), "EMPTY_COVERAGE", "no source lines were executed"
    )


def native_report(
    data_file: Path,
    report: Path,
    root: Path,
    sources: Sequence[str],
    xml_report: Path | None = None,
) -> dict[str, Any]:
    validate_data(data_file, root, sources)
    with in_directory(root):
        measured = coverage_instance(data_file, sources)
        measured.load()
        measured.json_report(outfile=str(report))
        if xml_report is not None:
            measured.xml_report(outfile=str(xml_report))
    return load_json(report)


def semantic_report(report: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(report))
    object_mapping(normalized.get("meta"), "report meta").pop("timestamp", None)
    return dict(normalized)


def _numbers(value: Any) -> frozenset[int]:
    require(
        isinstance(value, list) and all(type(item) is int for item in value),
        "INVALID_REPORT",
        "coverage line lists must contain integers",
    )
    return frozenset(value)


def _arcs(value: Any) -> frozenset[tuple[int, int]]:
    require(
        isinstance(value, list)
        and all(
            isinstance(item, list) and len(item) == 2 and all(type(n) is int for n in item)
            for item in value
        ),
        "INVALID_REPORT",
        "coverage branch arcs must be integer pairs",
    )
    return frozenset((item[0], item[1]) for item in value)


def report_universe(report: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    meta = object_mapping(report.get("meta"), "report meta")
    require(meta.get("branch_coverage") is True, "INVALID_REPORT", "branch report required")
    files = object_mapping(report.get("files"), "report files")
    require(bool(files), "INVALID_REPORT", "nonempty coverage files required")
    for name, entry in files.items():
        require(isinstance(name, str), "INVALID_REPORT", "coverage file names must be strings")
        object_mapping(entry, f"coverage entry {name}")
    return {
        name: (
            (_numbers(entry.get("executed_lines")) | _numbers(entry.get("missing_lines")))
            - _numbers(entry.get("excluded_lines")),
            _numbers(entry.get("excluded_lines")),
            _arcs(entry.get("executed_branches")) | _arcs(entry.get("missing_branches")),
        )
        for name, entry in files.items()
    }


def verify_receipt(
    receipt: dict[str, Any],
    dialect: str,
    data: Path,
    report: Path,
    source: dict[str, Any],
    root: Path,
    sources: Sequence[str],
) -> None:
    require(
        receipt.get("schema") == SCHEMA and receipt.get("status") == "PASS",
        "PRODUCER_NOT_PASSED",
        f"{dialect} has no successful coverage execution receipt",
    )
    require(
        receipt.get("dialect") == dialect, "DIALECT_MISMATCH", f"receipt must measure {dialect}"
    )
    execution = object_mapping(receipt.get("execution"), "execution receipt")
    require(
        type(execution.get("exit_code")) is int and execution["exit_code"] == 0,
        "PRODUCER_NOT_PASSED",
        f"{dialect} producer did not exit successfully",
    )
    require(
        receipt.get("coverage_version") == locked_version(),
        "COVERAGE_VERSION",
        "receipt version differs from lock",
    )
    require(
        receipt.get("source_before") == source
        and receipt.get("source_after_sha256") == source["sha256"],
        "SOURCE_MISMATCH",
        f"{dialect} execution measured different source bytes or source changed during execution",
    )
    require(
        receipt.get("sources") == list(sources)
        and receipt.get("coverage_config") == config_text(sources),
        "COVERAGE_CONFIG",
        f"{dialect} execution used a different source/configuration",
    )
    require(
        receipt.get("run") == run_identity(),
        "RUN_MISMATCH",
        f"{dialect} execution belongs to another repository/SHA/run/attempt",
    )
    artifacts = object_mapping(receipt.get("artifacts"), "receipt artifacts")
    for kind, path in (("data", data), ("report", report)):
        require(
            artifacts.get(kind) == {"path": relative_path(root, path), "sha256": sha256(path)},
            "ARTIFACT_MISMATCH",
            f"{dialect} {kind} does not match its execution receipt: {path}",
        )
