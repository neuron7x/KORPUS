"""Fail-closed validation of *metadata-only* public reference leads.

This validator never downloads, indexes, quotes or authenticates source content.
Structural PASS is deliberately distinct from corpus/production authorization.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
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
    if "\\" in url:
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
        row["access_model"] in {"PUBLIC_LANDING", "PUBLIC_CATALOG_AUTH_CONTENT", "UNKNOWN"}
        and row["reuse_status"] == "UNASSESSED"
        and row["integration_mode"] == "METADATA_ONLY"
    )


def verify_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    """Reject unknown rights or escalation fields; preserve zero admission by design."""
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValueError("missing, symlinked or oversized catalog")
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            if len(records) >= MAX_ROWS:
                raise ValueError("source count exceeds bounded maximum")
            try:
                row = json.loads(line, object_pairs_hook=_unique, parse_constant=_nonfinite)
            except (ValueError, UnicodeError) as exc:
                errors.append(f"line {line_number}: invalid JSON: {exc}")
                continue
            if not _valid_row(row):
                errors.append(f"line {line_number}: invalid metadata-only source record")
                continue
            records.append(row)
        if not records:
            errors.append("empty catalog")
        ids = [row["source_id"] for row in records]
        urls = [row["url"] for row in records]
        if len(set(ids)) != len(ids) or len(set(urls)) != len(urls):
            errors.append("duplicate source id or canonical URL")
    except (OSError, UnicodeError, ValueError) as exc:
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
