# KORPUS engineering first principles — 2026

These are KORPUS rules, not quotations or claimed prescriptions from any individual.
They are an applied interpretation of engineering patterns visible in small reference
systems such as `micrograd`, `llm.c`, and `nanochat`: keep the main path legible,
retain a reference path, make complexity earn its cost, and use executable comparison
rather than aesthetic confidence.

## 1. Minimal complete path before machinery

A feature is not promoted because a framework exists for it. First preserve the
smallest end-to-end path that can be executed, inspected, and falsified. Abstractions
are admitted only when they remove repeated verified complexity or enforce a boundary.

## 2. Reference behavior before optimization

Every optimization that can alter semantics needs a reference behavior, invariant, or
frozen evaluation set. Faster-but-different is a new mechanism and must be tested as one.

## 3. Complexity is a cost function

Line count is not the objective, but hidden branching, duplicated policy, dependency
surface, and configuration multiplicity are costs. A change that adds those costs must
show a measured capability, reliability, security, or maintenance gain. KORPUS keeps a
module/function complexity ratchet; shrinking is free, growth is evidence-bearing.

## 4. One semantic source, multiple execution surfaces

GitHub Actions, legacy GitLab CI, local Make targets, containers, and production are not
allowed to define independent meanings of a gate. Execution surfaces invoke repository
scripts/Make targets; policy logic belongs in source where it can be tested once.

## 5. Determinism where determinism is possible

Dependency bytes, action revisions, base images, release identity, package manifests,
and generated contracts are pinned or hashed. Runtime nondeterminism must be measured
and bounded rather than hidden behind retries.

## 6. Negative controls are mandatory for gates

A check that has only ever passed is not known to detect its target failure. New gates
ship with a mutation, malformed fixture, attack case, or other negative control proving
that the predicate can become false.

## 7. Experimental complexity stays at the edge

Exploration may be locally complex. Promotion into the default execution path requires
simplification, explicit interfaces, bounded failure modes, and evidence. Experimental
code does not silently become infrastructure by accumulation.

## 8. Evidence is release-bound

Detection, execution, and solution are distinct states. Historical evidence keeps its
original release/environment attribution. A new tag inherits source lineage, not fresh
measurements. Production authorization remains false until production-class gates are
current and independently satisfied.
