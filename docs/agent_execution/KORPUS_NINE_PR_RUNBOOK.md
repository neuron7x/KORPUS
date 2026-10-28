# KORPUS — Nine-PR Agent Execution Runbook

Status: PROPOSED / NOT IMPLEMENTED. Published through GitHub connector on 2026-10-28.
Controller: https://github.com/neuron7x/KORPUS/issues/97
Canonical code: https://github.com/neuron7x/KORPUS
Baseline inspected: main 16d768830067e1644118bb089c7878aab177d54b
Refresh the current main, Issues, PR heads and branch-protection controls before ANY execution. The baseline above is historical context, never a future authorization.

## Purpose and topology

Close the *acceptance conditions* of the 24 original open Issues through nine independently reviewable, causal implementation work packages. An existing source-level fix is not the same as executable acceptance evidence. A green CI job is not live corpus recovery, production authorization or a verified deployment.

This file is the index, role contract, sequencing protocol and bootstrap prompt. Detailed phase-specific attack cases, source surfaces, test gates and DONE definitions live in the primary GitHub execution Issues below, not in arbitrary agent output.

| Implementation phase | Primary agent Issue | Original Issues | Scope |
|---|---|---|---|
| PR-01 | https://github.com/neuron7x/KORPUS/issues/98 | #23 #26 #27 | Temporal snapshot, semantic release and candidate visibility |
| PR-02 | https://github.com/neuron7x/KORPUS/issues/99 | #25 #31 | PostgreSQL RLS and approval provenance |
| PR-03 | https://github.com/neuron7x/KORPUS/issues/100 | #35 | Immutable source-bound learning graph |
| PR-04 | https://github.com/neuron7x/KORPUS/issues/101 | #43 | Corpus admission, off-host backup and restore |
| PR-05 | https://github.com/neuron7x/KORPUS/issues/102 | #66 | Verified GitHub run/attempt/job/artifact evidence |
| PR-06 | https://github.com/neuron7x/KORPUS/issues/103 | #67 | GitHub OIDC/Sigstore signature and trust-root verification |
| PR-07 | https://github.com/neuron7x/KORPUS/issues/104 | #8 | Immutable GitHub-native signed release |
| PR-08 | https://github.com/neuron7x/KORPUS/issues/105 | #3 #4 #6 #7 #12 #14 #16 #18 #20 #21 #22 #52 #83 | Full historical release/package/military-readiness/pilot falsification |
| PR-09 | https://github.com/neuron7x/KORPUS/issues/106 | #51 | Authorized real GCP HTTPS/deployment/rollback evidence |

24 original acceptance Issues map to exactly one primary agent issue. Each primary issue owns ONE isolated worktree/branch/implementation PR in accordance with AGENTS.md. A PR can reference multiple original acceptance Issues; that does not create extra placeholder PRs.

Current implementation: existing draft https://github.com/neuron7x/KORPUS/pull/95 is PR-01. Unrelated Dependabot https://github.com/neuron7x/KORPUS/pull/96 stays outside the nine implementation units. This documentation-only runbook PR, if opened, is PR-00 and is NOT one of nine engineering implementations.

## First-principles dependency and trust graph

AUTHORIZED DATABASE IDENTITY + APPROVED CANONICAL SOURCE
    -> ONE MONOTONIC CORPUS STATE
    -> AUTHORIZED CANDIDATES AND EVIDENCE
    -> ANSWER + CITATIONS + AUDIT BOUND TO THE SAME SNAPSHOT

TRACKED SOURCE + EXECUTION ORCHESTRATION
    -> ACTUALLY EXECUTED TESTS / MUTATIONS / COVERAGE
    -> CANONICAL RUN + JOB + ATTEMPT
    -> DOWNLOADED ARTIFACT ID + VERIFIED MEMBER BYTES
    -> PINNED CRYPTOGRAPHIC ATTESTATION AND TRUST ROOT
    -> FROZEN VERIFIED ZIP
    -> SIGNED RELEASE CLAIM
    -> SEPARATE OWNER AUTHORIZATION AND REAL CORPUS
    -> PROVEN LIVE SERVICE / RECOVERY / ROLLBACK

Different arrows are different proof obligations. Never replace one with another.

- An answer state label is not an atomic state read.
- Application-controlled SQL settings are not independent database authorization.
- SHA-256 equality is not evidence of who executed a job.
- A signature is only meaningful with verified trust/issuer/subject identity.
- Verified bytes must equal hashed and signed bytes, including race/path-swap negatives.
- A health response, Terraform validation or passing CI cannot establish live production readiness.

## Dependency ordering

01 -> 02 -> 03 -> 04 (corpus code and test checks).
05 -> 06 -> 07 (independent hosted evidence / cryptographic branch).
08 after all available accepted source and cryptographic code from 01–07.
09 only after 08, real admitted corpus/restore and explicit owner approval.

The actual PR merge base is always the latest verified canonical main SHA, never a stale historical draft. PR-04 may finish code while its original Issue #43 remains OPEN / BLOCKED_EXTERNAL for absent real backup or authorized corpus material. PR-05/06 can continue in that case; do not turn unavailable corpus into invented PASS.

## Operating roles: separation of duties

**Coordinator** reads canonical main, the original issue obligations, the primary phase ticket, required CI contexts and existing PR state. It maintains a DAG and issues an implementation scope but does not authorize merge or production.

**Builder** uses one isolated worktree, writes the smallest causal patch, records exact changed paths, adds negative + positive tests, regenerates source-bound derived identities and opens/updates exactly one scoped implementation PR. Reuse a working mechanism when the original Issue predates current main.

**Falsifier** is a separate pass that attempts to kill the asserted invariant using deterministic poison tests and genuine runtime evidence, without touching production data. It can return FAIL/INCONCLUSIVE even when source passes superficial tests.

**Independent Auditor** fetches source, exact candidate SHA, real hosted run/attempt/job logs, test counts and skipped cases, artifact byte hashes, mutations, module/coverage ratchets and unresolved review threads. It does not accept the Builder's self-attested PASS.

**Owner / merge controller** retains final approval of merge, secrets, deployment, external data access, publication and production authorization. Green tests do not grant any of these rights.

## Per-phase execution algorithm

1. READ: Obtain current main and primary/original Issues, open PR, exact required checks, branch protection, relevant code, tests and migrations. Record BASE_SHA.
2. MODEL: Identify the trust boundary and threat/failure model. Write a minimal counterexample and formal invariant before editing.
3. FALSIFY: Execute existing negative controls on current main where safe. Record actual BEFORE result; do not fabricate a failing baseline if code already prevents the attack.
4. IMPLEMENT: Choose ALREADY_FIXED_IN_MAIN + acceptance proof, minimal test addition, or minimal causal repair. Do not redesign unrelated subsystems.
5. MUTATION: Add a specific critical mutant when a new security/consistency predicate would otherwise not be independently exercised. Unkilled critical mutant blocks merge.
6. REBIND: After code and tests are frozen, regenerate the impacted source and desired-state identities and PACKAGE_BUILD in producer-before-consumer order; never hand-edit reported hashes to green a gate.
7. EXECUTE: Run focused positive/negative tests, real PostgreSQL under actual unprivileged roles when required, strict lint/module budget, migrations, deterministic replay, coverage/critical mutation and hosted exact-candidate CI.
8. AUDIT: Independently read check names, run/attempt, skipped/failed jobs, artifact source SHA and bytes, review threads and open blockers. Green status from another SHA is not evidence.
9. HANDOFF: Write phase-specific output including machine-readable provenance and issue-by-issue verdict, request human merge approval, and do not advance based on a draft merge assumption.
10. CLOSE: Re-evaluate each original Issue's acceptance items against actual execution. Only owner-approved merged code plus complete acceptance allows closing an original Issue.

Do not repeatedly rerun the same failure hoping for luck; investigate the root cause. No global ignore, reduced coverage/mutation budgets, skip/xfail, fake benchmark, degraded authorization or broad file exclusion to force PASS.

## CI gate names observed on 2026-10-28 (refresh before each PR)

- api-quality
- api-tests
- repository-contract
- web-tests
- assurance / postgres-full-suite
- assurance / research-assurance
- dependency-review
- verify-production-contract
- CodeQL
- Analyze (actions)
- Analyze (javascript-typescript)
- Analyze (python)

Also inspect GCP contract validation and any newly required checks. All required check contexts must be successful for the exact candidate (including changes introduced by concurrent PRs). Distinguish SKIPPED from PASS.

Repository entry points available: make api-lint, make api-test, make validate, make check, make postgres-suite, make production-postgres-security, make mutation, make eval, make military-readiness-full, make release-verify, make release-verify-closure, make determinism-gate and make web-build. Select focused tests from the actual diff; do not claim a local command executed when only GitHub-hosted evidence exists. Producer-before-consumer ordering is required.

Generated-source conventions: python3 scripts/generate_desired_state.py (only if relevant inputs changed); python3 scripts/generate_manifest.py; python3 scripts/sync_package_build_identity.py; validate the desired state, source manifest and package build identity. A generated report from a different SHA is stale, even when its status field says PASS.

## Mandatory evidence handoff

Every implementation PR must provide at least the following observed fields, with linked raw logs/artifacts and negative tests:

phase / primary_issue / original_issues
base_sha / head_sha / synthetic_candidate_sha
changed_paths / exact source-manifest root
commands / exit_codes / positive_controls / poison_controls
GitHub workflow identity / run_id / run_attempt / producer_job_id
artifact_id / archive_digest / verified_member_byte_receipts
coverage_statement / coverage_branch / skipped_tests / unexecuted_gates
mutants_defined / mutants_killed / critical_mutants_survived
external_blockers / independent_review / merge_admission / issue_disposition
production_authorized = false unless separate genuine production permission is established

Evidence classification:
- PASS — executable, source-bound, positive + adversarial proof for the precise predicate.
- FAIL — observed counterexample or required gate failed.
- INCONCLUSIVE — insufficient discrimination between hypotheses.
- NOT_EXECUTED — no runtime evidence exists; never count it as PASS.
- ALREADY_FIXED_IN_MAIN — source inspected and attack re-executed on current main.
- BLOCKED_EXTERNAL — exact real data, infrastructure or owner authorization absent.

Never auto-close original Issues from planning comments. If new counterexamples require a separate root-cause PR, revise the dependency graph honestly; nine is an execution hypothesis, not a claim that no new finding can arise.

## Bootstrap agent instruction (English)

ROLE: Principal KORPUS Safety-Engineering Orchestrator / Independent Audit Controller

Repository: https://github.com/neuron7x/KORPUS
Controller: https://github.com/neuron7x/KORPUS/issues/97
Active start: https://github.com/neuron7x/KORPUS/issues/98
Current implementation candidate: https://github.com/neuron7x/KORPUS/pull/95

OBJECTIVE: Carry out the nine-phase acceptance program with evidence-first, fail-closed, minimal-diff engineering and separate Builder / Falsifier / Independent Auditor passes.

STARTUP: Refresh exact origin/main, AGENTS.md, primary execution issue, all linked original acceptance Issues, current PRs/CI required contexts and source manifest policy. Compare every Issue's historical claim with today's actual main implementation. Read this runbook and the full phase ticket.

FOR EACH PHASE:
A. Draw the causal trust boundary, observable invariant and minimal attack in one screen.
B. Run a deterministic negative control against current main. Record what actually happened.
C. If already closed in source, add missing acceptance tests only; otherwise make a minimal targeted repair and inspect the entire change.
D. Preserve strict type/lint/module/coverage/security/critical mutation ratchets.
E. Regenerate exact desired/source/package identity only after freezing source.
F. Run focused tests, relevant real PostgreSQL/hosted checks and full exact-candidate required CI. Preserve actual exit codes and source/worker/log identity.
G. Have a distinct auditor review raw negative/positive evidence and every required check.
H. Update one implementation PR, link primary+original Issues, attach machine-readable handoff, request owner merge approval and STOP at merge gate.
I. Use actual merged canonical main before advancing; do not infer a merge from a green draft.

NEVER:
- push directly to protected main, force-push, auto-merge or self-authorize deployment;
- import private corpus objects, production secrets or restricted materials into GitHub;
- relabel old or foreign test/evidence artifacts as a new candidate;
- treat unrun tests, synthetic fixtures, stale run receipts, unverified signatures or missing external restore as PASS;
- weaken gate enforcement or resurrect obsolete GitLab release/deployment authority.

FINAL:
Provide an exact 24-item acceptance ledger. Each must have actual merged-implementation and current execution proof or a precisely named blocker. Without an owner-authorized live corpus/HTTPS/backup/rollback demonstration, use BLOCKED_EXTERNAL / NOT_AUTHORIZED rather than production PASS.
