"""Fail-closed validation of *metadata-only* public reference leads.

This validator never downloads, indexes, quotes or authenticates source content.
Structural PASS is deliberately distinct from corpus/production authorization.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "config/kb/reference_sources.jsonl"
MAX_BYTES = 128 * 1024
MAX_ROWS = 256
FIELDS = frozenset(
    {
        "source_id",
        "title",
        "publisher",
        "url",
        "category_ids",
        "access_model",
        "reuse_status",
        "integration_mode",
    }
)
CATEGORIES = frozenset(
    {
        "T01_INSTRUCTOR_METHODS",
        "T02_FIRST_AID_EDUCATION",
        "T03_HUMANITARIAN_LAW",
        "T04_CIVIL_EMERGENCY_PREPAREDNESS",
        "T05_SYSTEMS_SAFETY_AND_RELIABILITY",
        "T06_DEFENSIVE_DIGITAL_HYGIENE",
        "T07_DATA_PROVENANCE_AND_RIGHTS",
        "T08_WELLBEING_SUPPORT",
        "T09_ADMIN_AND_CIVIL_LOGISTICS",
        "T10_AGENT_ENGINEERING",
    }
)
SOURCE_ID = re.compile(r"SRC_[A-Z0-9_]{2,64}\Z")
HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_PERCENT_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _canonical_path(path: str) -> str:
    """RFC 3986-safe comparison key: decode only unreserved percent escapes.

    Reserved escapes retain their boundary; path case and literal double slashes
    remain significant. Only dot segments (including encoded dots) are removed.
    """

    def decode_unreserved(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else "%" + match.group(1).upper()

    value = _PERCENT_ESCAPE.sub(decode_unreserved, path or "/")
    segments = value.split("/")
    stack = [""]
    for index, segment in enumerate(segments[1:], 1):
        if segment in {".", ".."}:
            if segment == ".." and len(stack) > 1:
                stack.pop()
            if index == len(segments) - 1:
                stack.append("")
        else:
            stack.append(segment)
    return "/".join(stack)


def _canonical_source_url(url: str) -> tuple[str | None, str]:
    parts = urlsplit(url)
    return parts.hostname, _canonical_path(parts.path)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise ValueError("nonfinite number")


def _public_https_url(url: object) -> bool:
    """Syntax-only: NOT a network/egress authorization or a DNS safety check."""
    if not isinstance(url, str) or not url or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        return False
    if "\\" in url or re.search(r"%(?![0-9A-Fa-f]{2})", url):
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname
        if (
            parts.scheme != "https"
            or not host
            or parts.port is not None
            or parts.fragment
            or parts.query
            or parts.username is not None
            or parts.password is not None
        ):
            return False
        if host.endswith((".", ".local", ".internal", ".localhost", ".lan")) or len(host) > 253:
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            return len(labels) >= 2 and all(HOST_LABEL.fullmatch(label) for label in labels)
        return False
    except ValueError:
        return False


def _valid_row(row: object) -> bool:
    if not isinstance(row, dict) or set(row) != FIELDS:
        return False
    if not isinstance(row["source_id"], str) or not SOURCE_ID.fullmatch(row["source_id"]):
        return False
    if not all(
        isinstance(row[key], str)
        and 2 <= len(row[key].strip()) <= 200
        and row[key] == row[key].strip()
        for key in ("title", "publisher")
    ):
        return False
    if not _public_https_url(row["url"]):
        return False
    categories = row["category_ids"]
    if (
        not isinstance(categories, list)
        or not 1 <= len(categories) <= 3
        or len(categories) != len(set(str(value) for value in categories))
        or not all(isinstance(value, str) and value in CATEGORIES for value in categories)
    ):
        return False
    return (
        isinstance(row["access_model"], str)
        and row["access_model"] in {"PUBLIC_LANDING", "PUBLIC_CATALOG_AUTH_CONTENT", "UNKNOWN"}
        and row["reuse_status"] == "UNASSESSED"
        and row["integration_mode"] == "METADATA_ONLY"
    )


def _read_catalog(path: Path) -> str:
    """Read one bounded regular-file descriptor, refusing final-component symlinks.

    Parent directories must be trusted. Metadata comparisons detect observable
    concurrent writes; they do not claim a filesystem-level atomic snapshot.
    """
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    if not nofollow or not nonblock:
        raise ValueError("safe catalog opening is unsupported on this platform")
    descriptor = os.open(path, os.O_RDONLY | nofollow | nonblock)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            raise ValueError("nonregular or oversized catalog")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(MAX_BYTES + 1)
        after = os.fstat(descriptor)
        if len(data) > MAX_BYTES:
            raise ValueError("catalog exceeds bounded byte maximum")
        fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(data) != before.st_size or any(
            getattr(before, key) != getattr(after, key) for key in fields
        ):
            raise ValueError("catalog changed during bounded read")
        return data.decode("utf-8")
    finally:
        os.close(descriptor)


def verify_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    """Reject unknown rights or escalation fields; preserve zero admission by design."""
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(_read_catalog(path).split("\n"), 1):
            if not line.strip(" \t\r"):
                continue
            if len(records) + len(errors) >= MAX_ROWS:
                raise ValueError("catalog row count exceeds bounded maximum")
            try:
                row = json.loads(line, object_pairs_hook=_unique, parse_constant=_nonfinite)
            except (ValueError, UnicodeError, RecursionError) as exc:
                errors.append(f"line {line_number}: invalid JSON: {exc}")
                continue
            if not _valid_row(row):
                errors.append(f"line {line_number}: invalid metadata-only source record")
                continue
            records.append(row)
        if not records:
            errors.append("empty catalog")
        ids = [row["source_id"] for row in records]
        # URI scheme/DNS host are case-insensitive; normalize unreserved/path aliases.
        urls = [_canonical_source_url(row["url"]) for row in records]
        if len(set(ids)) != len(ids) or len(set(urls)) != len(urls):
            errors.append("duplicate source id or canonical URL")
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        errors.append(str(exc))
    return {
        "gate": "PUBLIC_REFERENCE_METADATA_STRUCTURE",
        "structure_status": "PASS" if not errors else "FAIL",
        "candidate_status": "BLOCKED",
        "source_records": len(records),
        "rights_cleared": 0,
        "acquired": 0,
        "reviewed": 0,
        "indexable": 0,
        "production_authorized": False,
        "network_access_performed": False,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    result = verify_catalog(args.catalog)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["structure_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
