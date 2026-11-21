"""One execution-receipt predicate for local combination and hosted admission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCHEMA = "korpus.dialect-coverage-execution.v1"


class CoverageContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise CoverageContractError(code, message)


def object_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CoverageContractError("INVALID_REPORT", f"{name} must be an object")
    return value


@dataclass(frozen=True)
class ReceiptSubject:
    dialect: str
    version: str
    source: dict[str, Any]
    sources: tuple[str, ...]
    configuration: str
    run: dict[str, str]
    artifacts: dict[str, dict[str, str]]


def verify_execution(receipt: dict[str, Any], dialect: str) -> None:
    require(
        receipt.get("schema") == SCHEMA and receipt.get("status") == "PASS",
        "PRODUCER_NOT_PASSED",
        f"{dialect} has no successful coverage execution receipt",
    )
    require(
        receipt.get("dialect") == dialect,
        "DIALECT_MISMATCH",
        f"receipt must measure {dialect}",
    )
    execution = object_mapping(receipt.get("execution"), "execution receipt")
    require(
        type(execution.get("exit_code")) is int and execution["exit_code"] == 0,
        "PRODUCER_NOT_PASSED",
        f"{dialect} producer did not exit successfully",
    )


def verify_subject(receipt: dict[str, Any], subject: ReceiptSubject) -> None:
    verify_execution(receipt, subject.dialect)
    require(
        receipt.get("coverage_version") == subject.version,
        "COVERAGE_VERSION",
        "receipt version differs from lock",
    )
    require(
        receipt.get("source_before") == subject.source
        and receipt.get("source_after_sha256") == subject.source["sha256"],
        "SOURCE_MISMATCH",
        f"{subject.dialect} execution measured different source bytes or changed during execution",
    )
    require(
        receipt.get("sources") == list(subject.sources)
        and receipt.get("coverage_config") == subject.configuration,
        "COVERAGE_CONFIG",
        f"{subject.dialect} execution used a different source/configuration",
    )
    require(
        receipt.get("run") == subject.run,
        "RUN_MISMATCH",
        f"{subject.dialect} execution belongs to another repository/SHA/run/attempt",
    )
    require(
        receipt.get("artifacts") == subject.artifacts,
        "ARTIFACT_MISMATCH",
        f"{subject.dialect} artifacts do not match their execution receipt",
    )
