"""Bounded diagnostic output handling; these observations cannot authorize a release."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any, cast

from scripts.source_security_contract import require, strict_json

SCHEMA = "korpus.scanner-engine-diagnostic.v1"
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_EXPORT_BYTES = 64 * 1024 * 1024
LABELS = (
    "stdlib-version",
    "release-version",
    "stdlib-utf8",
    "release-utf8",
    "stdlib-history-intact",
    "release-history-intact",
    "stdlib-history-damaged",
    "release-history-damaged",
    "release-full-history",
)
FINDING_FIELDS = frozenset(
    {
        "RuleID",
        "Description",
        "StartLine",
        "EndLine",
        "StartColumn",
        "EndColumn",
        "Match",
        "Secret",
        "File",
        "SymlinkFile",
        "Commit",
        "Link",
        "Entropy",
        "Author",
        "Email",
        "Date",
        "Message",
        "Tags",
        "Fingerprint",
        "Fragment",
    }
)


def diagnostic_receipt() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "INCOMPLETE_DIAGNOSTIC",
        "not_authoritative": True,
        "production_authorized": False,
        "drop_in_equivalence_established": False,
        "eof_status": "NOT_INDEPENDENTLY_OBSERVED",
        "scope": "alternate fixed release binary measurement; no scanner admission",
        "performance_ratio_established": False,
        "engine_causality_established": False,
        "raw_native_output_exported": False,
        "raw_cpu_profiles_exported": False,
    }


def read_output(path: Path, root: Path) -> bytes:
    require(
        path.is_relative_to(root)
        and ".." not in path.parts
        and path.resolve().is_relative_to(root.resolve())
        and not root.is_symlink(),
        "output escapes owned storage",
    )
    require(
        all(not parent.is_symlink() for parent in path.parents if parent.is_relative_to(root)),
        "symlink parent in native output",
    )
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(info.st_mode) and info.st_size <= MAX_OUTPUT_BYTES,
            "native output is nonregular or oversized",
        )
        raw = stream.read(MAX_OUTPUT_BYTES + 1)
    require(len(raw) == info.st_size, "native output changed while reading")
    return raw


def parse_findings(raw: bytes) -> list[dict[str, Any]]:
    value = strict_json(raw)
    require(isinstance(value, list), "native diagnostic report is not a findings list")
    require(
        all(
            isinstance(item, dict)
            and set(item) <= FINDING_FIELDS
            and item.get("Secret") == "REDACTED"
            and isinstance(item.get("Match"), str)
            and isinstance(item.get("RuleID"), str)
            and isinstance(item.get("File"), str)
            and item.get("Fragment") is None
            for item in value
        ),
        "native finding is malformed or does not redact its secret",
    )
    return cast(list[dict[str, Any]], value)


def findings(output: Path) -> list[dict[str, Any]]:
    return parse_findings(read_output(output / "gitleaks.json", output))


def native_diagnostics(log: bytes, exit_code: int) -> dict[str, bool]:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", log.decode("utf-8", errors="replace"))
    lowered = text.lower()
    return {
        "parent_timeout_observed": exit_code == 124 or "SOURCE_SECURITY_TIMEOUT" in text,
        "native_deadline_message_observed": any(
            marker in lowered for marker in ("deadline exceeded", "timeout reached", "partial scan")
        ),
        "native_error_message_observed": re.search(r"(?:^|\s)(?:ERR|FTL)\b", text) is not None
        or any(
            marker in lowered
            for marker in (
                "command aborted",
                "error reading",
                "bad object",
                "unable to read",
                "fatal:",
            )
        ),
    }


def full_observation(execution: dict[str, Any], output: Path) -> dict[str, Any]:
    log = read_output(output / "gitleaks.log", output)
    diagnostics = native_diagnostics(log, execution["exit_code"])
    result: dict[str, Any] = {
        "execution": execution,
        "eof_status": "NOT_INDEPENDENTLY_OBSERVED",
        **diagnostics,
        "history_completion_established": False,
        "container_peak_memory_bytes": None,
        "container_oom_status": "NOT_OBSERVED",
        "partial_or_failed": any(diagnostics.values()) or execution["exit_code"] != 0,
    }
    try:
        result["finding_count"] = len(findings(output))
        result["native_report_valid"] = True
        result["findings_observed"] = result["finding_count"] > 0
        result["zero_exit_with_findings"] = (
            execution["exit_code"] == 0 and result["findings_observed"]
        )
        result["partial_or_failed"] = result["partial_or_failed"] or result["findings_observed"]
    except (OSError, ValueError):
        result.update(native_report_valid=False, finding_count=None, partial_or_failed=True)
    return result


def export_outputs(source: Path, destination: Path) -> dict[str, Any]:
    # Resolve after this module initializes: the shared projection uses its readers.
    from scripts.scanner_stdlib_result import export_labels

    result: dict[str, Any] = export_labels(
        source, destination, LABELS, ("release-full-history",), MAX_EXPORT_BYTES
    )
    return result
