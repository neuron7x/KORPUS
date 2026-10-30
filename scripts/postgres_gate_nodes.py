"""Fail-closed proof that every frozen PostgreSQL security pytest node executed."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

EXPECTED_CASES = 111
EXPECTED_FUNCTIONS = 69
CONTRACT = Path(__file__).with_name("postgres_gate_case_contract.json")
REPORT = Path("var/postgres-security/pytest-junit.xml")


def required_node_ids() -> set[tuple[str, str]]:
    """Read the source-tracked, explicitly frozen hosted collection contract."""
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    modules = data.get("modules")
    if (
        data.get("schema") != "korpus.postgres-security-node-contract.v1"
        or data.get("case_count") != EXPECTED_CASES
        or not isinstance(modules, dict)
    ):
        raise ValueError("invalid PostgreSQL node contract")
    pairs = [(module, name) for module, names in modules.items() for name in names]
    bases = {(module, name.split("[", 1)[0]) for module, name in pairs}
    if (
        len(pairs) != EXPECTED_CASES
        or len(set(pairs)) != EXPECTED_CASES
        or len(bases) != EXPECTED_FUNCTIONS
        or any(not name.startswith("test_") for _, name in pairs)
    ):
        raise ValueError("incomplete PostgreSQL node contract")
    return set(pairs)


def inspect_pytest_junit(root: Path) -> tuple[bool, int, list[str]]:
    """Require exact test identities and outcomes, never only total count."""
    try:
        required = required_node_ids()
        cases = ElementTree.parse(root / REPORT).findall(".//testcase")
    except (OSError, ValueError, TypeError, ElementTree.ParseError):
        return False, 0, ["missing_or_invalid_junit_or_node_contract"]
    seen: set[tuple[str, str]] = set()
    invalid = False
    for case in cases:
        module = case.attrib.get("classname", "").rsplit(".", 1)[-1]
        name = case.attrib.get("name", "")
        node = (module, name)
        if (
            node in seen
            or not name.startswith("test_")
            or any(case.find(tag) is not None for tag in ("skipped", "failure", "error"))
        ):
            invalid = True
        seen.add(node)
    missing = sorted(f"{module}::{name}" for module, name in required - seen)
    unexpected = sorted(f"unexpected:{module}::{name}" for module, name in seen - required)
    return (
        len(cases) == EXPECTED_CASES and not invalid and not missing and not unexpected,
        len(cases),
        missing + unexpected,
    )
