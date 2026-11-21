"""Export structural summaries; corpus-derived native text remains private."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from scripts import scanner_engine_result as native
from scripts.source_security_contract import require


def diagnostic_receipt() -> dict[str, Any]:
    return {
        "schema": "korpus.scanner-stdlib-diagnostic.v1",
        "status": "INCOMPLETE_DIAGNOSTIC",
        "not_authoritative": True,
        "production_authorized": False,
        "canonical_scanner_changed": False,
        "drop_in_equivalence_established": False,
        "history_completion_established": False,
        "eof_status": "NOT_INDEPENDENTLY_OBSERVED",
        "raw_native_output_exported": False,
        "raw_cpu_profiles_exported": False,
        "scope": "paired source-built stdlib measurements in the existing scanner sandbox",
    }


def _native_counts(raw: bytes) -> dict[str, int | None]:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw.decode(errors="replace"))
    fields = {
        "reported_commits": r"\b([0-9]{1,12}) commits scanned\.",
        "reported_bytes": r"\bscanned ~([0-9]{1,15}) bytes\b",
    }
    result = {}
    for name, pattern in fields.items():
        values = re.findall(pattern, text)
        result[name] = int(values[0]) if len(values) == 1 else None
    return result


def structural_summary(source: Path, relative: Path, raw: bytes) -> bytes:
    """Never publish corpus-derived strings, even when Secret is REDACTED."""
    label = (source / relative).relative_to(source)
    require(".." not in label.parts, "native summary label escapes its source")
    summary: dict[str, Any] = {
        "schema": "korpus.scanner-native-file-summary.v1",
        "source_name": label.as_posix(),
        "source_bytes": len(raw),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_content_exported": False,
    }
    if relative.name == "gitleaks.json":
        report = native.parse_findings(raw)
        summary["finding_count"] = len(report)
        summary["secret_redaction_checked"] = True
    elif relative.suffix == ".log":
        # These are log signals; the actual process exit status is recorded separately.
        summary["log_signals"] = native.native_diagnostics(raw, 0)
        summary.update(_native_counts(raw))
    return (json.dumps(summary, sort_keys=True, indent=2) + "\n").encode()


def export_labels(
    source: Path,
    destination: Path,
    labels: tuple[str, ...],
    profiles: tuple[str, ...],
    max_total: int,
) -> dict[str, Any]:
    """The two diagnostic callers supply closed label sets and the existing cap."""
    relatives = [Path("image-gitleaks.log")]
    relatives += [
        Path(label) / member
        for label in labels
        for member in ("execution.json", "gitleaks.log", "gitleaks.json")
    ]
    relatives += [Path(label) / "gitleaks-profile/cpu.pprof" for label in profiles]
    inventory, total = {}, 0
    for relative in relatives:
        path = source / relative
        if not path.exists() and not path.is_symlink():
            continue
        raw = native.read_output(path, source)
        total += len(raw)
        require(total <= max_total, "diagnostic export exceeds its total byte budget")
        safe = structural_summary(source, relative, raw)
        summary_path = relative.with_name(relative.name + ".summary.json")
        target = destination / "native" / summary_path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("xb") as stream:
            stream.write(safe)
        inventory[summary_path.as_posix()] = {
            "bytes": len(safe),
            "sha256": hashlib.sha256(safe).hexdigest(),
            "source_bytes": len(raw),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
        }
    return inventory


def export_outputs(source: Path, destination: Path) -> dict[str, Any]:
    labels = tuple(
        f"{stage}-{name}"
        for stage in ("control", "candidate")
        for name in ("version", "utf8", "positive", "full-history")
    )
    return export_labels(
        source,
        destination,
        labels,
        ("control-full-history", "candidate-full-history"),
        native.MAX_EXPORT_BYTES,
    )
