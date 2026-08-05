"""The register has to be a register, not a list that happens to run.

Three validators grew as runs of `if …: failures.append("…")`, and
`validate_infrastructure.main` reached a cyclomatic complexity of 102 that way. The
number was the symptom. Three properties were missing, and each is asserted here:

*A failure has a name.* Not a sentence appended where it happened — an id that can be
cited in an audit, marked accepted-with-risk by an owner, matched to a mutant, counted.

*Every requirement is evaluated.* Stopping at the first failure turns a review into a
queue: fix, re-run, discover the next.

*A broken predicate fails its requirement.* A missing `.dockerignore` excludes nothing;
a checker that raised instead would abort the run and report one problem where there
are twelve.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from korpus.application.requirements import (
    Requirement,
    as_catalogue,
    duplicate_ids,
    evaluate_requirements,
)
from korpus.infrastructure_requirements import INFRASTRUCTURE_REQUIREMENTS, load_context

ROOT = Path(__file__).resolve().parents[3]


def _requirement(identifier: str, holds) -> Requirement:
    return Requirement(
        id=identifier, subject="test", statement=f"{identifier} holds", holds=holds
    )


def test_the_shipped_infrastructure_register_is_satisfied() -> None:
    """The dual. A register nothing satisfies says nothing about anything."""
    report = evaluate_requirements(INFRASTRUCTURE_REQUIREMENTS, load_context(ROOT))

    assert report.satisfied, [failure.id for failure in report.unmet]
    assert report.total >= 100


def test_every_requirement_has_a_unique_id() -> None:
    """An id is how a requirement is cited; two sharing one makes every citation ambiguous."""
    assert duplicate_ids(INFRASTRUCTURE_REQUIREMENTS) == []


def test_duplicate_ids_are_actually_detected() -> None:
    """The register has no duplicates, so asserting over it alone proves nothing.

    Probed 2026-08-05: a mutant replacing the whole detector with `return []` survived
    the test above, because an empty result is the correct answer for a clean register.
    The detector has to be shown detecting.
    """
    duplicated = [
        _requirement("compose.api.read_only_root", lambda _: True),
        _requirement("ci.no_global_cache", lambda _: True),
        _requirement("compose.api.read_only_root", lambda _: True),
    ]

    assert duplicate_ids(duplicated) == ["compose.api.read_only_root"]


def test_every_requirement_states_a_property_rather_than_a_complaint() -> None:
    """Positive statements: a list of negations is read wrong under pressure.

    Not style. This list is what an outside assessor reads first, and "the API does not
    run privileged" scans as a finding while "the API does not run privileged" as a
    *requirement* scans as satisfied — the same words, opposite meanings, depending on
    which column the reader thinks they are in.
    """
    complaints = [
        requirement.id
        for requirement in INFRASTRUCTURE_REQUIREMENTS
        if requirement.statement.startswith(("missing", "no ", "must not", "forbidden"))
        and not requirement.statement.startswith("no job")
    ]
    assert complaints == [], complaints


def test_every_requirement_names_a_subject_and_states_something() -> None:
    empty = [
        requirement.id
        for requirement in INFRASTRUCTURE_REQUIREMENTS
        if not requirement.subject.strip() or len(requirement.statement.strip()) < 10
    ]
    assert empty == [], empty


def test_all_requirements_are_evaluated_not_just_up_to_the_first_failure() -> None:
    """A review that reports one problem at a time is a queue, not a report."""
    report = evaluate_requirements(
        [
            _requirement("first", lambda _: False),
            _requirement("second", lambda _: True),
            _requirement("third", lambda _: False),
        ],
        context=None,
    )

    assert [failure.id for failure in report.unmet] == ["first", "third"]
    assert report.total == 3


def test_a_predicate_that_raises_fails_its_own_requirement() -> None:
    """A `.dockerignore` that cannot be read excludes nothing.

    Letting the exception escape would abort the whole run at the first unreadable
    artefact and report one failure where there are twelve.
    """

    def explode(_context: object) -> bool:
        raise FileNotFoundError("infra/minio/korpus-app-policy.json")

    report = evaluate_requirements(
        [_requirement("reads-a-missing-file", explode), _requirement("fine", lambda _: True)],
        context=None,
    )

    assert [failure.id for failure in report.unmet] == ["reads-a-missing-file"]


def test_the_report_carries_the_id_and_the_reason() -> None:
    """A failure without its rationale sends the reader to `git blame` to find out why."""
    requirement = Requirement(
        id="compose.api.read_only_root",
        subject="docker-compose",
        statement="the API root filesystem is read-only",
        holds=lambda _: False,
        rationale="a writable root turns a parser bug into a persistent implant",
    )

    rendered = evaluate_requirements([requirement], context=None).as_dict()

    assert rendered["valid"] is False
    assert rendered["failures"][0]["id"] == "compose.api.read_only_root"
    assert "implant" in rendered["failures"][0]["rationale"]


def test_the_register_reads_as_a_document() -> None:
    """§2.5 asks an outside party to judge this system; they need the list first."""
    catalogue = as_catalogue(INFRASTRUCTURE_REQUIREMENTS)

    assert len(catalogue) == len(INFRASTRUCTURE_REQUIREMENTS)
    assert {"id", "subject", "statement", "rationale"} == set(catalogue[0])
    subjects = {entry["subject"] for entry in catalogue}
    assert {"docker-compose", "gitlab-ci", "backup", "build"} <= subjects


@pytest.mark.parametrize(
    "requirement_id",
    [
        "compose.api.read_only_root",
        "compose.worker.network_isolation",
        "ci.forbidden.privileged",
        "backup.streams_to_stdout",
        "dockerfile.api.hashed_lock",
        "minio.policy.no_destructive_actions",
    ],
)
def test_the_load_bearing_requirements_survived_the_move(requirement_id: str) -> None:
    """Named individually because each was a line in a 102-branch function.

    A refactor of a security validator is evidence only if the specific properties can
    be shown to have come through, not merely that the count looks right.
    """
    identifiers = {requirement.id for requirement in INFRASTRUCTURE_REQUIREMENTS}

    assert requirement_id in identifiers


def test_every_required_service_carries_the_full_hardening_set() -> None:
    """A service added without its checks is the gap the generated shape closes."""
    from korpus.infrastructure_requirements import REQUIRED_SERVICES

    identifiers = {requirement.id for requirement in INFRASTRUCTURE_REQUIREMENTS}
    for service in REQUIRED_SERVICES:
        for check in ("present", "unprivileged", "no_new_privileges", "resource_ceiling"):
            assert f"compose.{service}.{check}" in identifiers, f"{service} misses {check}"
