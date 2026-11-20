"""Bound native log evidence; a complete-looking summary does not prove input EOF."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

OUTPUT_MEMBERS = (
    "tree-sbom.cdx.json",
    "lock-sbom.cdx.json",
    "gitleaks.json",
    "gitleaks.log",
    "pip-audit-runtime.json",
    "pip-audit-dev.json",
    "trivy.json",
)
MAX_GITLEAKS_LOG_BYTES = 16 * 1024 * 1024
ANSI_SGR = re.compile(r"\x1b\[[0-9;]*m")
INFO_PREFIX = r"\d{1,2}:\d{2}(?:AM|PM) INF "
SUMMARY_PATTERNS = (
    re.compile(INFO_PREFIX + r"\d+ commits scanned\."),
    re.compile(INFO_PREFIX + r"scanned ~\d+ bytes \([^\r\n)]+\) in \S+"),
    re.compile(INFO_PREFIX + r"no leaks found"),
)
ERROR_MARKERS = (
    "command aborted",
    "error reading",
    "bad object",
    "unable to read",
    "fatal:",
    "panic:",
    "deadline exceeded",
    "timeout reached",
    "partial scan",
    "source_security_timeout",
    "source_security_execution_unavailable",
    "source_security_cleanup_unproven",
)


def read_native_log(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_GITLEAKS_LOG_BYTES:
            raise ValueError("Gitleaks native log is nonregular or oversized")
        raw = stream.read(MAX_GITLEAKS_LOG_BYTES + 1)
    if len(raw) != info.st_size:
        raise ValueError("Gitleaks native log changed while reading")
    return raw


def _reject_diagnostics(text: str) -> None:
    lowered = text.lower()
    if re.search(r"(?:^|\s)(?:ERR|FTL|PNC)\b", text) or any(
        marker in lowered for marker in ERROR_MARKERS
    ):
        raise ValueError("Gitleaks native log reports an input error or partial execution")


def validate_gitleaks_log(raw: bytes) -> None:
    if not 0 < len(raw) <= MAX_GITLEAKS_LOG_BYTES or not raw.endswith(b"\n"):
        raise ValueError("Gitleaks native log is empty, oversized or lacks its final newline")
    text = ANSI_SGR.sub("", raw.decode("utf-8"))
    if any((ord(char) < 32 and char not in "\n\t") or 127 <= ord(char) <= 159 for char in text):
        raise ValueError("Gitleaks native log contains unsupported control characters")
    _reject_diagnostics(text)
    lines = text.splitlines()
    positions = []
    for pattern in SUMMARY_PATTERNS:
        matches = [index for index, line in enumerate(lines) if pattern.fullmatch(line)]
        if len(matches) != 1:
            raise ValueError("Gitleaks native log lacks one complete success summary")
        positions.append(matches[0])
    if positions != sorted(positions) or positions[-1] != len(lines) - 1:
        raise ValueError("Gitleaks native log summary is reordered or lacks its terminal line")
