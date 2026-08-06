"""One shape for every requirement this system states about itself.

Three validators grew independently — infrastructure, repository, kubernetes — and a
fourth set lived inside `Settings`. Each was a run of `if …: failures.append("…")`, and
`validate_infrastructure.main` reached a cyclomatic complexity of 102 that way. The
number is a symptom; three things follow from the shape itself:

*The report cannot name what failed.* A string appended at the point of failure is the
only identity a check has, so a gate says "controlled environments require PostgreSQL"
and nothing connects that sentence to a rule anyone can look up, count, or mark as
accepted-with-risk.

*A mutant cannot reach one check.* The mutation catalogue works by editing a line and
demanding a test die. With a hundred checks in one function, a mutant either hits the
function or nothing, so ninety-nine of them are individually unfalsified.

*The requirements cannot be read.* §2.5 asks an outside assessor to judge this system.
What they need first is the list of things it claims about itself — not a program that
produces that list as a side effect of running.

So a requirement is data: an id, the subject it constrains, the property stated
positively, why it exists, and a predicate. Stating it positively matters — `holds`
is true when the deployment is acceptable — because a list of negations is read wrong
under pressure, and this list will be read under pressure.

The evaluator is deliberately dull. It applies predicates and collects ids. Everything
interesting lives in the registries, which are the documents.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Requirement:
    """One property, checkable, with the reason it is a property at all."""

    id: str
    subject: str
    statement: str
    holds: Callable[[Any], bool]
    rationale: str = ""
    #: What an operator is told when this requirement is unmet, when that differs from
    #: the statement. The statement is positive so the register reads as a list of
    #: properties; a failure often has to name what was actually found — which kinds
    #: were missing, which value the config carried — and that sentence cannot be
    #: written in advance for a register generated from a document set.
    failure: str = ""

    @property
    def message(self) -> str:
        return self.failure or self.statement

    def evaluate(self, context: Any) -> bool:
        """A predicate that raises has not been satisfied.

        A missing file or a malformed document is a failure of the requirement, not an
        error in the checker: `.dockerignore` that cannot be read excludes nothing.
        Letting the exception escape would abort the whole run at the first problem and
        report one failure where there are twelve.
        """
        try:
            return bool(self.holds(context))
        except Exception:  # noqa: BLE001 - the predicate's own failure is the answer
            return False


@dataclass(frozen=True)
class RequirementReport:
    total: int
    unmet: tuple[Requirement, ...]

    @property
    def satisfied(self) -> bool:
        return not self.unmet

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "valid": self.satisfied,
            "requirements_checked": self.total,
            "failures": [
                {
                    "id": requirement.id,
                    "subject": requirement.subject,
                    "statement": requirement.statement,
                    "rationale": requirement.rationale,
                }
                for requirement in self.unmet
            ],
        }


def evaluate_requirements(
    requirements: Iterable[Requirement], context: Any
) -> RequirementReport:
    """Every requirement is evaluated; the first failure does not stop the rest.

    Reporting one failure at a time turns a review into a queue: fix, re-run, discover
    the next. The whole point of a register is that somebody can see the whole state.
    """
    listed = tuple(requirements)
    unmet = tuple(requirement for requirement in listed if not requirement.evaluate(context))
    return RequirementReport(total=len(listed), unmet=unmet)


def duplicate_ids(requirements: Iterable[Requirement]) -> list[str]:
    """Ids that appear more than once.

    An id is how a requirement is cited in an audit, marked as accepted-with-risk, or
    matched to its mutant. Two requirements sharing one makes every such reference
    ambiguous, and the ambiguity is invisible in a passing run.
    """
    seen: dict[str, int] = {}
    for requirement in requirements:
        seen[requirement.id] = seen.get(requirement.id, 0) + 1
    return sorted(identifier for identifier, count in seen.items() if count > 1)


def as_catalogue(requirements: Iterable[Requirement]) -> list[Mapping[str, str]]:
    """The register as a document, for a reader rather than a run."""
    return [
        {
            "id": requirement.id,
            "subject": requirement.subject,
            "statement": requirement.statement,
            "rationale": requirement.rationale,
        }
        for requirement in requirements
    ]
