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

# A citation names one of two different things, and conflating them cost a week of
# pipelines. `apps/api/tests/test_x.py` is *in the tree*: every clone has it, and its
# absence is a defect anywhere. `var/mutation-report.json` is *produced by a run*: it
# does not exist in a fresh checkout and its absence before the producing job is the
# normal state, not a defect. Checking both in one place meant the check could only
# pass where a previous run had left files behind — green locally, red in CI from
# d894a89 to 12b550b, and red in a fresh clone for anyone who ever tried.
PRODUCED_PREFIX = "var/"


def is_produced_artifact(reference: str) -> bool:
    """True when the citation names a file a run writes, not a file the tree carries."""

    return split_reference(reference)[0].startswith(PRODUCED_PREFIX)


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


def verify_references(
    root: Path,
    references: Iterable[str],
    *,
    include_produced: bool = True,
) -> list[str]:
    """Return one message per citation that does not resolve.

    ``include_produced=False`` skips citations of run-produced artefacts, for callers
    that run before the producing step. It never skips a tree file: a caller cannot
    use this flag to excuse a missing test.
    """

    problems: list[str] = []
    for reference in references:
        if not include_produced and is_produced_artifact(reference):
            continue
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
    *,
    include_produced: bool = True,
) -> list[str]:
    """Verify every citation, and require executable evidence where closure is claimed.

    ``include_produced=False`` is for callers that run before the artefacts a run
    produces exist — the tree citations are still checked in full. The requirement
    that a produced artefact have a producer, and that whoever resolves it runs
    later, is enforced separately in ``test_gate_parity.py``: relaxing it here would
    otherwise let a citation name a file nothing ever writes.
    """

    problems: list[str] = []
    for finding_id in sorted(evidence):
        references = list(evidence[finding_id])
        problems.extend(
            f"{finding_id}: {message}"
            for message in verify_references(root, references, include_produced=include_produced)
        )
        if statuses.get(finding_id) in executable_statuses and not any(
            is_executable_evidence(reference) for reference in references
        ):
            problems.append(
                f"{finding_id}: claimed {statuses[finding_id]} with no test or CI job "
                "cited — a closure evidenced only by prose is a claim (ADR-0008)"
            )
    return problems
