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


def _check_wrapper_totals(wrapper: ElementTree.Element) -> None:
    """Reject inconsistent optional aggregate totals on a pytest testsuites root."""
    totals = [len(wrapper.findall("testsuite/testcase")), 0, 0, 0]
    for key, expected in zip(("tests", "skipped", "failures", "errors"), totals, strict=True):
        declared = wrapper.get(key)
        if declared is not None and declared != str(expected):
            raise ValueError("contradictory pytest wrapper totals")


def _validated_report_cases(path: Path) -> list[ElementTree.Element]:
    """Reject contradictory pytest suite totals before accepting individual nodes."""
    document = ElementTree.parse(path).getroot()
    suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
    if document.tag not in {"testsuite", "testsuites"} or len(suites) != 1:
        raise ValueError("unexpected pytest suite structure")
    cases = suites[0].findall("testcase")
    if len(cases) != len(document.findall(".//testcase")):
        raise ValueError("unexpected pytest testcase nesting")
    try:
        totals = [int(suites[0].attrib[key]) for key in ("tests", "skipped", "failures", "errors")]
    except (KeyError, ValueError) as error:
        raise ValueError("invalid pytest suite totals") from error
    if totals != [len(cases), 0, 0, 0]:
        raise ValueError("contradictory pytest suite totals")
    if document.tag == "testsuites":
        _check_wrapper_totals(document)
    return cases


def inspect_pytest_junit(root: Path) -> tuple[bool, int, list[str]]:
    """Require exact test identities and outcomes, never only total count."""
    try:
        required = required_node_ids()
        cases = _validated_report_cases(root / REPORT)
    except (OSError, ValueError, TypeError, ElementTree.ParseError):
        return False, 0, ["missing_or_invalid_junit_or_node_contract"]
    seen: set[tuple[str, str]] = set()
    invalid = False
    for case in cases:
        module = case.attrib.get("classname", "").removeprefix("tests.")
        name = case.attrib.get("name", "")
        node = (module, name)
        if (
            node in seen
            or case.attrib.get("classname", "") != f"tests.{module}"
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
