"""Strict arithmetic for JUnit suite cardinalities."""
from __future__ import annotations
import xml.etree.ElementTree as ET
_FIELDS = ("tests", "failures", "errors", "skipped")


def _count(raw: object, field: str) -> int:
    if raw is None: return 0
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal():
        raise ValueError(f"JUnit {field} must be an ASCII non-negative integer")
    try: return int(raw)
    except ValueError as exc: raise ValueError(f"JUnit {field} is outside the supported integer domain") from exc


def _suite_counts(suite: ET.Element) -> dict[str, int]:
    counts = {field: _count(suite.attrib.get(field), field) for field in _FIELDS}
    if counts["failures"] + counts["errors"] + counts["skipped"] > counts["tests"]:
        raise ValueError("JUnit outcome counts cannot exceed tests")
    return counts


def junit_counts(root: ET.Element) -> dict[str, int]:
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    totals = {field: 0 for field in _FIELDS}
    for suite in suites:
        counts = _suite_counts(suite)
        for field in _FIELDS: totals[field] += counts[field]
    return totals
