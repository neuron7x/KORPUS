"""Check that cited evidence exists and is executable.

Destruction stage 2026-08-03: ``build_audit_closure.py`` refused a locally-closed
finding only when its evidence list was *empty*. Nothing opened the files it
named. A registry that cites ``apps/api/tests/test_gone.py::test_removed`` and a
registry that cites a test which runs are the same document to a checker that
only counts list entries.

Two predicates are stated here. Every cited path must exist, and every cited
``path::test`` must name a test function that is actually defined in that file —
resolved with ``ast`` so a missing dependency cannot turn "cannot import" into
"nothing to check". And a finding claimed CLOSED must cite at least one test:
per ADR-0008 a closure is a test that fails when the property is violated, so a
closure evidenced only by prose is a claim, not a closure.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

TEST_ROOT = "apps/api/tests/"
CI_FILE = ".gitlab-ci.yml"


def split_reference(reference: str) -> tuple[str, str | None]:
    """Split ``path::selector`` into its parts; parametrization is stripped."""

    path, separator, selector = reference.partition("::")
    if not separator:
        return path, None
    return path, selector.split("[", 1)[0]


def _ci_job_names(path: Path) -> set[str]:
    """Job names are the top-level keys of the pipeline document.

    Read with a regex rather than a YAML parser: this check has to run in the same
    place the pipeline does, and pulling a parser in would put the check behind the
    install step whose absence is exactly the failure mode being guarded.
    """

    return {
        match.group(1)
        for match in re.finditer(
            r"^([A-Za-z][\w:.-]*):\s*$", path.read_text(encoding="utf-8"), re.MULTILINE
        )
    }


def _defined_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
    return names


def verify_references(root: Path, references: Iterable[str]) -> list[str]:
    """Return one message per citation that does not resolve."""

    problems: list[str] = []
    for reference in references:
        relative, selector = split_reference(reference)
        path = root / relative
        if not path.exists():
            problems.append(f"cited evidence does not exist: {reference}")
            continue
        if selector is None:
            continue
        if relative == CI_FILE:
            if selector not in _ci_job_names(path):
                problems.append(f"cited CI job does not exist: {selector}")
            continue
        if path.suffix != ".py":
            problems.append(
                f"{reference}: only .py tests and {CI_FILE} jobs can be cited by selector"
            )
            continue
        if selector not in _defined_names(path):
            problems.append(f"cited test is not defined in {relative}: {selector}")
    return problems


def is_executable_evidence(reference: str) -> bool:
    """A test that can fail, or a CI job that can block a merge (ADR-0008)."""

    relative, selector = split_reference(reference)
    if relative.startswith(TEST_ROOT):
        return True
    return relative == CI_FILE and selector is not None


def verify_closure_registry(
    root: Path,
    evidence: Mapping[str, Iterable[str]],
    statuses: Mapping[str, str],
    executable_statuses: frozenset[str] = frozenset({"CLOSED_LOCAL"}),
) -> list[str]:
    """Verify every citation, and require executable evidence where closure is claimed."""

    problems: list[str] = []
    for finding_id in sorted(evidence):
        references = list(evidence[finding_id])
        problems.extend(
            f"{finding_id}: {message}" for message in verify_references(root, references)
        )
        if statuses.get(finding_id) in executable_statuses and not any(
            is_executable_evidence(reference) for reference in references
        ):
            problems.append(
                f"{finding_id}: claimed {statuses[finding_id]} with no test or CI job "
                "cited — a closure evidenced only by prose is a claim (ADR-0008)"
            )
    return problems
