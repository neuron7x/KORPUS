"""Paired native stdlib controls; no alternate engine or admission authority."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from scripts.scanner_engine_commands import EngineSandbox
from scripts.scanner_engine_fixtures import checked_git, utf8_fixture
from scripts.scanner_engine_probes import canary_arguments
from scripts.scanner_engine_result import findings, native_diagnostics, read_output
from scripts.source_security_contract import require

RULE_IDS = frozenset({"generic-api-key", "gocardless-api-token", "lob-api-key", "lob-pub-api-key"})


def synthetic_positive_text() -> bytes:
    """Construct public test values at runtime; these have no issuing authority."""
    values = (
        ("api_key", "q7Nz9RW4" + "pfK2jm8B"),
        ("gocardless", "live_" + "q7Nz9RW4pfK2jm8B6sX1cV5tL0dH3eA9rY2uZ8iP"),
        ("lob", "live_" + "a9b7c5d3e1f02468a9b7c5d3e1f02468abc"),
        ("lob", "test_pub_" + "a9b7c5d3e1f02468a9b7c5d3e1f0246"),
    )
    return "".join(f'{name}="{value}"\n' for name, value in values).encode()


def positive_fixture(root: Path) -> str:
    root.mkdir(mode=0o700)
    checked_git(root, ["init", "--quiet", "--initial-branch=diagnostic", "--object-format=sha1"])
    (root / "positive.txt").write_bytes(synthetic_positive_text())
    checked_git(root, ["add", "--", "positive.txt"])
    checked_git(root, ["commit", "--quiet", "-m", "neutral stdlib rule controls"])
    return checked_git(root, ["rev-parse", "HEAD"]).decode().strip()


def normalized_findings(output: Path) -> tuple[list[dict[str, Any]], str]:
    records = findings(output)
    canonical = "\n".join(sorted(json.dumps(item, sort_keys=True) for item in records)).encode()
    return records, hashlib.sha256(canonical).hexdigest()


def positive_observation(record: dict[str, Any], output: Path) -> dict[str, Any]:
    raw = read_output(output / "gitleaks.log", output)
    markers = re.findall(r"using ([^\r\n]+?) regex engine", raw.decode(errors="replace"))
    diagnostics = native_diagnostics(raw, record["exit_code"])
    records, identity = normalized_findings(output)
    require(
        record["exit_code"] == 1 and markers == ["stdlib"] and not any(diagnostics.values()),
        "paired native positive control did not complete with the stdlib engine",
    )
    return {
        "execution": record,
        "engine_markers": markers,
        "finding_count": len(records),
        "finding_files": sorted(str(item["File"]) for item in records),
        "finding_rules": sorted({str(item["RuleID"]) for item in records}),
        "full_native_findings_sha256": identity,
    }


def paired_probes(sandboxes: dict[str, EngineSandbox]) -> dict[str, Any]:
    temporary = sandboxes["control"].temporary
    utf8 = temporary / "stdlib-utf8-fixture"
    positive = temporary / "stdlib-positive-fixture"
    utf8_head, positive_head = utf8_fixture(utf8), positive_fixture(positive)
    observations: dict[str, Any] = {"versions": {}, "utf8": {}, "positive": {}}
    for stage, sandbox in sandboxes.items():
        execution, output = sandbox.run(stage + "-version", ["version"], release=True)
        version = read_output(output / "gitleaks.log", output).decode().strip()
        require(execution["exit_code"] == 0 and version == "v8.30.1", "built version differs")
        observations["versions"][stage] = {"execution": execution, "reported_version": version}
        execution, output = sandbox.run(
            stage + "-utf8", canary_arguments(utf8_head), release=True, source=utf8
        )
        item = positive_observation(execution, output)
        require(
            item["finding_files"] == ["invalid.txt", "valid.txt"]
            and item["finding_rules"] == ["neutral-engine-boundary"],
            "stdlib UTF-8 boundary controls differ",
        )
        observations["utf8"][stage] = item
        arguments = canary_arguments(positive_head)
        index = arguments.index("--config")
        del arguments[index : index + 2]
        execution, output = sandbox.run(
            stage + "-positive", arguments, release=True, source=positive
        )
        item = positive_observation(execution, output)
        require(
            set(item["finding_rules"]) == RULE_IDS
            and all(name == "positive.txt" for name in item["finding_files"]),
            "optimized-rule positive control has missing or unexpected findings",
        )
        observations["positive"][stage] = item
    for name in ("utf8", "positive"):
        pair = observations[name]
        require(
            pair["control"]["full_native_findings_sha256"]
            == pair["candidate"]["full_native_findings_sha256"],
            "paired native finding records differ",
        )
    observations["identical_positive_and_utf8_records"] = True
    observations["fixture_heads"] = {"utf8": utf8_head, "positive": positive_head}
    observations["synthetic_positive_input_sha256"] = hashlib.sha256(
        synthetic_positive_text()
    ).hexdigest()
    return observations
