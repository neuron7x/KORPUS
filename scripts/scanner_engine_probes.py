"""Observed engine identity, UTF-8 divergence and a damaged-history falsification."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from scripts.scanner_engine_commands import EngineSandbox
from scripts.scanner_engine_fixtures import (
    CANARY_CONFIG,
    INVALID_TEXT,
    VALID_TEXT,
    damage_history,
    history_control,
    history_fixture,
    utf8_fixture,
)
from scripts.scanner_engine_result import findings, native_diagnostics, read_output
from scripts.source_security_contract import require

ENGINES = {"stdlib": "stdlib", "release": "github.com/wasilibs/go-re2"}


def canary_arguments(commit: str) -> list[str]:
    return [
        "detect",
        "--source",
        "/source",
        "--config",
        "/source/canary.toml",
        "--no-banner",
        "--redact",
        "--exit-code",
        "1",
        "--log-opts",
        f"{commit} --full-history --diff-merges=first-parent",
        "--report-format",
        "json",
        "--report-path",
        "/output/gitleaks.json",
        "--log-level",
        "debug",
        "--timeout",
        "15",
    ]


def versions(sandbox: EngineSandbox) -> dict[str, Any]:
    result = {}
    for name in ENGINES:
        record, output = sandbox.run(name + "-version", ["version"], release=name == "release")
        text = read_output(output / "gitleaks.log", output).decode("utf-8").strip()
        result[name] = {"execution": record, "reported_version": text}
        require(
            record["exit_code"] == 0 and re.fullmatch(r"v?8\.30\.1", text) is not None,
            "native version probe did not report the fixed release version",
        )
    return result


def _native_observation(record: dict[str, Any], output: Path, engine: str) -> dict[str, Any]:
    raw = read_output(output / "gitleaks.log", output)
    log = raw.decode("utf-8", errors="replace")
    markers = re.findall(r"using ([^\r\n]+?) regex engine", log)
    observation: dict[str, Any] = {
        "execution": record,
        "expected_engine": ENGINES[engine],
        "engine_marker_count": markers.count(ENGINES[engine]),
        "observed_engine_markers": markers,
        "engine_identity_consistent": markers == [ENGINES[engine]],
        "diagnostics": native_diagnostics(raw, record["exit_code"]),
    }
    try:
        report = findings(output)
        require(
            all(
                item.get("RuleID") == "neutral-engine-boundary" and item.get("Match") == "REDACTED"
                for item in report
            ),
            "neutral probe reported an unexpected rule",
        )
        observation.update(
            native_report_valid=True,
            finding_files=sorted(str(item.get("File")) for item in report),
        )
    except (OSError, ValueError):
        observation.update(native_report_valid=False, finding_files=None)
    return observation


def utf8_probe(sandbox: EngineSandbox) -> dict[str, Any]:
    source = sandbox.temporary / "utf8-fixture"
    head = utf8_fixture(source)
    result: dict[str, Any] = {
        "fixture_head": head,
        "rule_sha256": hashlib.sha256(CANARY_CONFIG).hexdigest(),
        "valid_input_sha256": hashlib.sha256(VALID_TEXT).hexdigest(),
        "invalid_input_sha256": hashlib.sha256(INVALID_TEXT).hexdigest(),
        "observations": {},
        "expected_divergence_observed": False,
    }
    for name in ENGINES:
        record, output = sandbox.run(
            name + "-utf8", canary_arguments(head), release=name == "release", source=source
        )
        result["observations"][name] = _native_observation(record, output, name)
        require(record["exit_code"] in {0, 1}, "neutral UTF-8 probe execution is incomplete")
    expected = {"stdlib": ["invalid.txt", "valid.txt"], "release": ["valid.txt"]}
    result["expected_divergence_observed"] = all(
        item["execution"]["exit_code"] == 1
        and item["engine_identity_consistent"] is True
        and item["native_report_valid"]
        and item["finding_files"] == expected[name]
        and not any(item["diagnostics"].values())
        for name, item in result["observations"].items()
    )
    return result


def damaged_history_probe(sandbox: EngineSandbox) -> dict[str, Any]:
    source = sandbox.temporary / "history-fixture"
    identity = history_fixture(source)
    result: dict[str, Any] = {"fixture": identity, "observations": {}}
    for state in ("intact", "damaged"):
        if state == "damaged":
            damage_history(source, identity)
        controls = history_control(source, identity["head"])
        require(
            all((item["exit_code"] == 0) == (state == "intact") for item in controls.values()),
            "independent Git controls did not establish the fixture's intended state",
        )
        observed: dict[str, Any] = {"independent_git": controls}
        result["observations"][state] = observed
        for name in ENGINES:
            record, output = sandbox.run(
                name + "-history-" + state,
                canary_arguments(identity["head"]),
                release=name == "release",
                source=source,
            )
            observation = _native_observation(record, output, name)
            observed[name] = observation
            require(record["exit_code"] in {0, 1}, "neutral history probe execution is incomplete")
            require(
                observation["engine_identity_consistent"], "native history engine is unverified"
            )
            if state == "intact":
                require(
                    record["exit_code"] == 1
                    and observation["engine_identity_consistent"]
                    and observation["finding_files"] == ["deleted.txt"]
                    and not any(observation["diagnostics"].values()),
                    "intact native control did not find the deleted historical marker",
                )
    result["interpretation"] = (
        "Native exit, findings and error messages are observations, not proof of error propagation; "
        "canonical history EOF remains NOT_INDEPENDENTLY_OBSERVED."
    )
    return result
