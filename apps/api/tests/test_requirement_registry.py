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


def _repository_validation_context() -> str:
    """Use distribution semantics only when exercising an actual FULL SSOT package."""
    return (
        "FULL_SSOT_DISTRIBUTION"
        if (ROOT / "FULL_SSOT_PACKAGE_RECEIPT.json").is_file()
        else "SOURCE_CHECKOUT"
    )


def _requirement(identifier: str, holds) -> Requirement:
    return Requirement(id=identifier, subject="test", statement=f"{identifier} holds", holds=holds)


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


def test_the_shipped_repository_register_is_satisfied() -> None:
    """The second validator, same shape, same dual."""
    from korpus.repository_requirements import REPOSITORY_REQUIREMENTS
    from korpus.repository_requirements import load_context as load_repository_context

    report = evaluate_requirements(
        REPOSITORY_REQUIREMENTS, load_repository_context(ROOT, _repository_validation_context())
    )

    assert report.satisfied, [failure.id for failure in report.unmet]
    assert report.total >= 90


def test_ids_are_unique_across_every_register() -> None:
    """The registers are separate files and one document; a collision spans them.

    Uniqueness inside each was already asserted. Two registers each internally clean
    can still both define `repo.file.readme`, and the id is how a requirement is cited
    — the ambiguity would live in the export, not in either source.
    """
    from korpus.controlled_requirements import CONTROLLED_REQUIREMENTS
    from korpus.repository_requirements import REPOSITORY_REQUIREMENTS

    everything = [
        *INFRASTRUCTURE_REQUIREMENTS,
        *REPOSITORY_REQUIREMENTS,
        *[
            _requirement(f"controlled.{requirement.name}", lambda _: True)
            for requirement in CONTROLLED_REQUIREMENTS
        ],
    ]

    assert duplicate_ids(everything) == []


def test_one_walk_answers_every_filesystem_question() -> None:
    """Three requirements read one traversal; three traversals would answer the same
    question three times over thirteen thousand paths."""
    from korpus.repository_requirements import load_context as load_repository_context

    context = load_repository_context(ROOT, _repository_validation_context())

    assert context.path_count == sum(1 for _ in ROOT.rglob("*"))
    assert context.oversized == []
    assert context.placeholders == []
    assert context.tracked_secrets == []


def test_the_kubernetes_register_states_the_same_rules_as_the_gate() -> None:
    """The register and the gate must be one thing, not two that agree today.

    `manifest_violations` is now a projection of `kubernetes_requirements`, so the only
    way they can disagree is if someone reintroduces an inline check. The first draft of
    the register restated REQUIRED_KINDS instead of importing it and named five kinds
    where the deployment names nine — a register that gates a smaller set than the
    deployment needs reads exactly like one that gates the right set.
    """
    from korpus.application.deployment import (
        REQUIRED_KINDS,
        REQUIRED_PRODUCTION_CONFIG,
        REQUIRED_WORKLOADS,
        render_kustomization,
    )
    from korpus.kubernetes_requirements import (
        KubernetesContext,
        kubernetes_requirements,
        manifest_violations,
    )

    root = Path(__file__).resolve().parents[3]
    rendered = render_kustomization(root / "deploy/kubernetes/base", root)
    requirements = kubernetes_requirements(KubernetesContext.build(rendered))

    assert manifest_violations(rendered) == []
    assert not duplicate_ids(requirements)
    # One requirement per required config key, not one for "the config".
    config_ids = {r.id for r in requirements if r.subject == "ConfigMap"}
    assert len(config_ids) == len(REQUIRED_PRODUCTION_CONFIG)
    statements = " ".join(r.statement for r in requirements)
    for kind in REQUIRED_KINDS:
        assert kind in statements
    for workload in REQUIRED_WORKLOADS:
        assert any(r.subject == workload for r in requirements), workload


def test_an_empty_render_reports_one_failure_rather_than_the_whole_register() -> None:
    """Twenty failures describing an empty input is a report nobody reads to the end."""
    from korpus.kubernetes_requirements import (
        KubernetesContext,
        kubernetes_requirements,
        manifest_violations,
    )

    requirements = kubernetes_requirements(KubernetesContext.build([]))

    assert len(requirements) == 1
    assert manifest_violations([]) == ["no Kubernetes resources"]


def test_a_failure_names_one_container_of_one_workload() -> None:
    """The id is what an assessor cites and what a mutant reaches.

    "the deployment has a violation" cannot be marked accepted-with-risk by an owner;
    `k8s.workload.korpus-api.container.0.read_only_root` can.
    """
    from korpus.kubernetes_requirements import KubernetesContext, kubernetes_requirements

    document = {
        "kind": "Deployment",
        "metadata": {"name": "korpus-api"},
        "spec": {"template": {"spec": {"containers": [{"image": "x"}, {"image": "y"}]}}},
    }
    requirements = kubernetes_requirements(KubernetesContext.build([document]))

    identifiers = {r.id for r in requirements}
    assert "k8s.workload.korpus-api.container.0.read_only_root" in identifiers
    assert "k8s.workload.korpus-api.container.1.read_only_root" in identifiers


def test_a_deployed_configuration_that_drifts_from_policy_is_reported() -> None:
    """A register that lists the config keys is not the same as one that checks them.

    The first version of this test counted the requirements and asserted the base
    deployment passes. Mutant M137 replaced the config predicate with `True` and
    survived: a register can name every key and still assert nothing about their values.
    """
    from korpus.application.deployment import REQUIRED_PRODUCTION_CONFIG
    from korpus.kubernetes_requirements import manifest_violations

    key, value = next(iter(REQUIRED_PRODUCTION_CONFIG.items()))
    configmap = {
        "kind": "ConfigMap",
        "metadata": {"name": "korpus-config"},
        "data": {**REQUIRED_PRODUCTION_CONFIG, key: "wrong"},
    }

    violations = manifest_violations([configmap])

    assert f"secure production config missing: {key}={value}" in violations
    # And the ones that are correct are not reported, or the message means nothing.
    for other_key, other_value in REQUIRED_PRODUCTION_CONFIG.items():
        if other_key != key:
            assert f"secure production config missing: {other_key}={other_value}" not in violations


def test_a_missing_configmap_reports_every_required_key() -> None:
    """Absent configuration is not compliant configuration."""
    from korpus.application.deployment import REQUIRED_PRODUCTION_CONFIG
    from korpus.kubernetes_requirements import manifest_violations

    violations = manifest_violations([{"kind": "Namespace", "metadata": {"name": "korpus"}}])

    for key, value in REQUIRED_PRODUCTION_CONFIG.items():
        assert f"secure production config missing: {key}={value}" in violations


def test_no_requirement_is_stated_twice_under_two_ids() -> None:
    """Four registers, 319 requirements, one namespace.

    An id is how a requirement is cited in an audit, marked accepted-with-risk by an
    owner, or matched to its mutant. Two ids stating the same property make every such
    reference ambiguous and inflate the count an assessor reads — and the check for
    duplicate *ids* does not catch it, because the ids differ.

    Checked across all four registers together, since they were separate accidents of
    where the code happened to live and are one document to a reader.
    """
    from collections import Counter

    from korpus.application.deployment import render_kustomization
    from korpus.controlled_requirements import CONTROLLED_REQUIREMENTS
    from korpus.infrastructure_requirements import INFRASTRUCTURE_REQUIREMENTS
    from korpus.kubernetes_requirements import KubernetesContext, kubernetes_requirements
    from korpus.repository_requirements import REPOSITORY_REQUIREMENTS

    root = Path(__file__).resolve().parents[3]
    deployment = kubernetes_requirements(
        KubernetesContext.build(render_kustomization(root / "deploy/kubernetes/base", root))
    )
    registered = [
        *INFRASTRUCTURE_REQUIREMENTS,
        *REPOSITORY_REQUIREMENTS,
        *deployment,
    ]

    assert not duplicate_ids(registered)

    statements = Counter(requirement.statement for requirement in registered)
    assert [text for text, count in statements.items() if count > 1] == []

    names = Counter(requirement.name for requirement in CONTROLLED_REQUIREMENTS)
    assert [name for name, count in names.items() if count > 1] == []
    messages = Counter(requirement.message for requirement in CONTROLLED_REQUIREMENTS)
    assert [message for message, count in messages.items() if count > 1] == []
