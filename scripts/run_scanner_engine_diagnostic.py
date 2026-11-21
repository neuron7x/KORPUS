"""Run a separate, nonauthoritative native engine experiment with no admission output."""

from __future__ import annotations

import http.client
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "apps/api/src")]

from scripts.scanner_engine_artifact import acquire_binary  # noqa: E402
from scripts.scanner_engine_commands import EngineSandbox  # noqa: E402
from scripts.scanner_engine_probes import damaged_history_probe, utf8_probe, versions  # noqa: E402
from scripts.scanner_engine_result import (  # noqa: E402
    diagnostic_receipt,
    export_outputs,
    full_observation,
)
from scripts.scanner_engine_subject import scanner_policy, workflow_subject  # noqa: E402
from scripts.source_security_container import cleanup_valid  # noqa: E402
from scripts.source_security_contract import require  # noqa: E402
from scripts.source_security_gitleaks import gitleaks_arguments  # noqa: E402
from scripts.source_security_source import (  # noqa: E402
    admit_source,
    runner_temporary,
    verify_source_after,
)

EXPECTED_FAILURES = (
    OSError,
    ValueError,
    subprocess.SubprocessError,
    tarfile.TarError,
    http.client.HTTPException,
)


def _experiment(root: Path, output: Path, receipt: dict[str, Any]) -> None:
    receipt["stage"] = "source-admission"
    before, files = admit_source(root)
    receipt.update(before)
    receipt["workflow_subject"] = workflow_subject(before)
    receipt["policy"] = scanner_policy(root)
    deadline = time.monotonic() + 20 * 60
    try:
        with TemporaryDirectory(
            prefix="korpus-engine-diagnostic-", dir=runner_temporary(root)
        ) as raw:
            temporary = Path(raw)
            native_output = temporary / "native-output"
            native_output.mkdir(mode=0o700)
            (temporary / "docker-config").mkdir(mode=0o700)
            try:
                receipt["stage"] = "fixed-release-download"
                binary, identity = acquire_binary(temporary / "binary")
                receipt["release"] = identity
                sandbox = EngineSandbox(
                    root, native_output, temporary, binary, identity["binary_sha256"], deadline
                )
                receipt["executions"] = sandbox.executions
                _measure(sandbox, before["source_commit_sha"], receipt)
                sandbox.verify_binary()
                receipt["binary_unchanged_after_measurement"] = True
            finally:
                require(
                    all(cleanup_valid(item) for item in receipt.get("executions", [])),
                    "unproven container cleanup prevents native output export",
                )
                try:
                    receipt["output_inventory"] = export_outputs(native_output, output)
                except EXPECTED_FAILURES:
                    receipt["stage"] = "safe-native-output-export"
                    raise
    finally:
        try:
            receipt["source_after_sha256"] = verify_source_after(root, before, files)
        except EXPECTED_FAILURES:
            receipt["stage"] = "source-after-verification"
            raise


def _measure(sandbox: EngineSandbox, commit: str, receipt: dict[str, Any]) -> None:
    receipt["stage"] = "pinned-image-provisioning"
    receipt["image_provisioning"] = sandbox.pull_image()
    receipt["stage"] = "native-version-observations"
    receipt["versions"] = versions(sandbox)
    receipt["stage"] = "native-utf8-observations"
    receipt["utf8"] = utf8_probe(sandbox)
    require(
        receipt["utf8"]["expected_divergence_observed"] is True,
        "paired native UTF-8 observations did not establish the expected semantic difference",
    )
    receipt["stage"] = "native-history-error-observations"
    receipt["damaged_history"] = damaged_history_probe(sandbox)
    receipt["stage"] = "alternate-full-history-invocation"
    execution, output = sandbox.run(
        "release-full-history", gitleaks_arguments(commit), release=True
    )
    receipt["full_history"] = full_observation(execution, output)
    require(
        not receipt["full_history"]["partial_or_failed"],
        "alternate native invocation did not produce a clean valid diagnostic result",
    )
    receipt["status"] = "RECORDED_NONAUTHORITATIVE"
    receipt["stage"] = "measurement-recorded"


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
        _experiment(root, output, receipt)
    except EXPECTED_FAILURES as error:
        receipt["status"] = "INCOMPLETE_DIAGNOSTIC"
        # Network exception text can contain signed redirect query strings.
        receipt["failure_class"] = type(error).__name__
    with (output / "diagnostic.json").open("x") as stream:
        stream.write(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return receipt


def main() -> int:
    receipt = produce(ROOT, ROOT / "var/scanner-engine-diagnostic")
    print(json.dumps({key: receipt[key] for key in ("status", "not_authoritative", "eof_status")}))
    return 0 if receipt["status"] == "RECORDED_NONAUTHORITATIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
