"""Measure a pinned stdlib precheck without producing scanner admission evidence."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "apps/api/src")]

from scripts.scanner_engine_commands import EngineSandbox  # noqa: E402
from scripts.scanner_engine_result import full_observation  # noqa: E402
from scripts.scanner_engine_subject import scanner_policy, workflow_subject  # noqa: E402
from scripts.scanner_stdlib_build import build_pair  # noqa: E402
from scripts.scanner_stdlib_probes import paired_probes  # noqa: E402
from scripts.scanner_stdlib_result import diagnostic_receipt, export_outputs  # noqa: E402
from scripts.source_security_container import cleanup_valid  # noqa: E402
from scripts.source_security_contract import require  # noqa: E402
from scripts.source_security_gitleaks import gitleaks_arguments  # noqa: E402
from scripts.source_security_source import (  # noqa: E402
    admit_source,
    runner_temporary,
    verify_source_after,
)

EXPECTED_FAILURES = (OSError, ValueError, subprocess.SubprocessError)


def measure(sandboxes: dict[str, EngineSandbox], commit: str, receipt: dict[str, Any]) -> None:
    receipt["stage"] = "pinned-image-provisioning"
    receipt["image_provisioning"] = sandboxes["control"].pull_image()
    receipt["stage"] = "paired-native-controls"
    receipt["controls"] = paired_probes(sandboxes)
    receipt["full_history"] = {}
    for name, sandbox in sandboxes.items():
        receipt["stage"] = name + "-native-full-history"
        execution, output = sandbox.run(
            name + "-full-history", gitleaks_arguments(commit), release=True
        )
        receipt["full_history"][name] = full_observation(execution, output)
        sandbox.verify_binary()
    require(
        not receipt["full_history"]["candidate"]["partial_or_failed"],
        "candidate native invocation did not produce a clean diagnostic observation",
    )
    receipt["status"] = "RECORDED_NONAUTHORITATIVE"
    receipt["stage"] = "measurement-recorded"


def experiment(root: Path, output: Path, receipt: dict[str, Any]) -> None:
    receipt["stage"] = "source-admission"
    before, files = admit_source(root)
    receipt.update(before)
    receipt["workflow_subject"] = workflow_subject(before)
    receipt["policy"] = scanner_policy(root)
    deadline = time.monotonic() + 20 * 60
    try:
        receipt["stage"] = "embedded-rule-configuration"
        override = root / ".gitleaks.toml"
        require(
            not override.exists() and not override.is_symlink(),
            "source-provided Gitleaks configuration is outside this default-rule diagnostic",
        )
        receipt["source_configuration_override_absent"] = True
        with TemporaryDirectory(
            prefix="korpus-stdlib-diagnostic-", dir=runner_temporary(root)
        ) as raw:
            temporary = Path(raw)
            native = temporary / "native-output"
            native.mkdir(mode=0o700)
            (temporary / "docker-config").mkdir(mode=0o700)
            receipt["executions"], receipt["build"] = [], {}
            try:
                receipt["stage"] = "source-pinned-paired-build"
                binaries = build_pair(root, temporary, receipt["build"])
                sandboxes = {
                    name: EngineSandbox(
                        root,
                        native,
                        temporary,
                        binary,
                        receipt["build"]["variants"][name]["binary_sha256"],
                        deadline,
                        receipt["executions"],
                    )
                    for name, binary in binaries.items()
                }
                measure(sandboxes, before["source_commit_sha"], receipt)
            finally:
                require(
                    all(cleanup_valid(item) for item in receipt["executions"]),
                    "unproven container cleanup prevents diagnostic export",
                )
                receipt["output_inventory"] = export_outputs(native, output)
    finally:
        receipt["source_after_sha256"] = verify_source_after(root, before, files)


def produce(root: Path, output: Path) -> dict[str, Any]:
    require(
        root.is_absolute()
        and output.is_absolute()
        and output.is_relative_to(root)
        and ".." not in output.parts
        and output.resolve().is_relative_to(root.resolve())
        and all(not parent.is_symlink() for parent in output.parents),
        "diagnostic destination is outside the checkout or has a symlink parent",
    )
    output.mkdir(parents=True, mode=0o700)
    receipt: dict[str, Any] = diagnostic_receipt()
    try:
        experiment(root, output, receipt)
    except EXPECTED_FAILURES as error:
        receipt["status"] = "INCOMPLETE_DIAGNOSTIC"
        receipt["failure_class"] = type(error).__name__
    with (output / "diagnostic.json").open("x") as stream:
        stream.write(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return receipt


def main() -> int:
    receipt = produce(ROOT, ROOT / "var/scanner-stdlib-diagnostic")
    print(
        json.dumps(
            {key: receipt[key] for key in ("status", "stage", "not_authoritative", "eof_status")}
        )
    )
    return 0 if receipt["status"] == "RECORDED_NONAUTHORITATIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
