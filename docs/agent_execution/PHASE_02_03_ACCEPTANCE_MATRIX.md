# Phase 02 / 03 acceptance evidence

Audit date: 2026-11-21. Scope: synthetic fixtures and generic database invariants.
Phase 02 is **PENDING_NATIVE_QUALIFICATION**. Phase 03 has executed baseline
controls and remains **DEPENDENCY_PENDING** on accepted phase 02.
`production_authorized = false`. This document does not close an issue.

The immediate parent is the published phase-01 candidate
`20c6b6ce361ecf041f6b8973089540dcc0a6ddfe`
([PR #138](https://github.com/neuron7x/KORPUS/pull/138)), which is still awaiting
acceptance. The dependent PR permits native phase-02 CI to run on the combined
tree; phase-02 merge admission still requires phase 01 to pass and merge first.

Acceptance owners: [#99](https://github.com/neuron7x/KORPUS/issues/99),
[#25](https://github.com/neuron7x/KORPUS/issues/25),
[#31](https://github.com/neuron7x/KORPUS/issues/31),
[#100](https://github.com/neuron7x/KORPUS/issues/100), and
[#35](https://github.com/neuron7x/KORPUS/issues/35).

## Executed baseline and its limits

| Identity | Observed value |
|---|---|
| Historical merged baseline for the prior evidence | `921ac8b9f2c71aa366c7d2b8c73206b696e9903c` |
| PR #137 head recorded by GitHub | `ed8c75877524fa0384aa01e18067339788aa93a0` |
| Tested merge checkout | `fc6d1b0d54bad87b6e07895ebe6bb0a50d004d28` |
| Tree shared by those three commits | `00562c890a73492b88a1234ed526fad7825acca3` |
| Hosted execution | [CI run 44874776733, attempt 1](https://github.com/neuron7x/KORPUS/actions/runs/44874776733/attempts/1) |
| Artifact | [14695996419, postgres-diagnostics-1](https://github.com/neuron7x/KORPUS/actions/runs/44874776733/artifacts/14695996419) |
| Downloaded ZIP | 1,138,789 bytes; SHA-256 `9147b1f162700aac2569865cb02086f8fef7ae2fc310ba319d1e6a0a5408ff09` |
| Full PostgreSQL JUnit | `pytest-postgres.xml`: 7,472 nodes = 7,465 passed + 7 skipped; zero failures/errors |
| Mandatory security JUnit | `postgres-security/pytest-junit.xml`: **129 / 129 passed**, zero skipped/failures/errors |
| Security gate | `production/postgres_security-gate.json`: PASS, all five checks true, observed/expected 129, runtime exit 0 |
| Full-suite execution receipt | `coverage-postgres-receipt.json`: PASS, command exit 0, source unchanged during execution |

This is evidence for an identical source tree, not a claim that the merge commit
itself executed that run. The new tests below were absent from this artifact.
Do not reuse its 129-pass result as qualification of the new candidate.

The full-suite receipt records:

```sh
python -m pytest -q -p no:cacheprovider apps/api/tests \
  --junitxml=var/pytest-postgres.xml --cov=apps/api/src/korpus \
  --cov-branch --cov-report=json:var/coverage-postgres.json \
  --cov-report= --cov-fail-under=0
```

The focused receipt records `bash scripts/run_postgres_suite.sh --targeted`
with the ten baseline targets from `scripts/run_postgres_security_gate.py`.
Its clean bootstrap reached `0028_reviewer_update_scope`, including temporal
guards (0019), broker identity (0020), approval provenance (0022), sealed
provenance (0025), learning history (0026), and competency immutability (0027).

## Phase 02: approval provenance and RLS

| Acceptance criterion | Baseline observation | Remaining obligation |
|---|---|---|
| #25.1: app cannot UPDATE both `review_state='approved'` and a chosen 64-hex seal | Catalog denials and INSERT attacks passed; the exact combined UPDATE was not executed | **NOT_EXECUTED:** new `test_app_update_cannot_forge_approval_and_evidence_seal` must pass natively |
| #25.2: authorized review atomically seals exact persisted evidence and audit | Exact-span seal test and separated reviewer positives passed; failed tier update rolled back review/audit | Retain those positives; each new case also executes separated metadata/content/approval and recomputes the persisted-span digest |
| #25.3: once-sealed digest cannot change or clear before/after rejection | Existing changed-digest attacks used the fixture owner; no NULL-seal attack established the requested runtime-role boundary | **NOT_EXECUTED:** eight new cases cover app/review x approved/rejected x changed/NULL |
| #25.4: migrated/runtime guard parity with exact grants | Clean migrated bootstrap, runtime guard initialization and 30 approval-provenance nodes passed | Fresh candidate must rerun the native suite; this does not admit a populated production migration |
| #25.5: preserve ceilings and authorization boundary | No runtime, migration, privilege or budget changes in this patch; local module budget passes | Fresh hosted required checks and independent execution audit; production remains unauthorized |
| #31: app cannot increase any claim axis or read a hidden row | Four claim-forgery nodes and the five independent app-axis cases in 35 claim-mutation nodes passed | Retain role/clearance/corpus/classification/compartment negatives in fresh CI |
| #31: app cannot acquire INSERT/UPDATE/DELETE authority through claims | Protected writer-path and isolated visibility-axis attacks in the 35-node module passed | Retain exact native identities and observed row denials |
| #31: review login cannot exceed intended scope | Review-axis/broker/column controls plus 15 reviewer-scope nodes passed, including WITH CHECK and pool reuse | Retain configured/custom-role positives and review-only scope denials |
| #31: legitimate app/review flows continue | Native integration and reviewer-only metadata/content/approval positives passed | New attacks must leave the same row able to complete legitimate review |
| #31: RLS enabled/forced; broker/context/policy boundary intact | Six policy-state nodes, three role-reprovision nodes and binder/context-table denials passed | No weakened grant, policy, search path or fallback is permitted |
| #31: focused/full native execution and supporting gates | Baseline focused 129/129 and full suite exit 0; the seven unrelated skips are listed below | New candidate requires 138/138 focused native PASS, full CI and phase-01 acceptance |
| #31: production authorization remains false | No deployment, production credential or real corpus used | Remains false independently of test results |

The full-suite approval/reviewer/integration group is 30 + 15 + 1 = 46 passed
nodes. It is not 46 independent approval-forgery attacks: many of the 30 nodes
inspect column grants. The dedicated 129-node gate did not include the separate
15-node reviewer-scope module.

### New native witnesses

`apps/api/tests/test_postgres_approval_seal_boundary.py` reuses the provisioned
app/review/authz identities from `review_postgres_support.py`. Document creation,
review, attempted DML and state observations use runtime connections; the owner
is only the existing disposable-fixture reset identity.

Each attack proves one visible target and one permitted `state_version` UPDATE
before the poison statement. The review login also successfully writes the
unchanged seal. Expected denials are app `42501` and review `P0001` with the
sealed-digest diagnostic. Explicit rollback must preserve the complete version,
persisted spans and audit rows, including the preceding permitted write.

Per-node JUnit properties record physical current/session login, PostgreSQL
version, migration revision, non-superuser/non-bypass/non-owner membership,
broker-bound subject/roles, SQLSTATE, review/state/seal before and after, and
evidence/audit row counts. Positive review requires three different subjects,
the exact recomputed seal and its audit payload.

The frozen mandatory contract is now **138 cases / 76 functions**, retaining all
129 prior nodes and adding these nine. Collection matched exactly: no missing or
unexpected IDs. Removing the new target is itself rejected by the gate contract.
No new runtime predicate or arbitrary duplicate mutant was introduced.

Local validation: 46 passed (44 contract + 2 orchestration), **9 skipped**,
zero failures/errors. All nine skips say the disposable native PostgreSQL suite
is required. PostgreSQL, psql and Docker are unavailable locally. Ruff check,
Ruff formatting, `git diff --check` and module budget passed. These observations
are collection/orchestration proof only; **none of the nine new DB attacks has
executed yet**. A separate agent reviewed the source changes; hosted execution
and the owner merge decision remain pending.

## Phase 03: immutable source-bound course graph

All four #35 controls have baseline native evidence. The application-role proof
contains **91 passed / zero skipped** nodes: persistence 37, scope/lifecycle 15,
concurrency 18, and the PostgreSQL subset of competency integrity 21. Each carries
PostgreSQL `170010`, role `korpus_app`, false superuser/bypass/owner inheritance,
and migration revision `0028_reviewer_update_scope`. Fixtures assert identical
current/session login and full graph-table DML grants, so immutability refusals
are not substitutes for missing write permission.

| #35 control | Executed positive and destruction evidence | Status at the recorded baseline |
|---|---|---|
| 1. Valid acyclic exact-source graph publishes | Repository and direct-SQL publication, exact document/version/span round-trip, distinct next revision | PASS |
| 2. Dangling/cyclic graph rejected | Cycle `23514`; dangling prerequisite/unknown version/span `23503`; rejected publication leaves draft state intact | PASS |
| 3. Invalid source blocks publication | Unapproved, rescinded, expired, future, document/span mismatch and unbound lesson controls; scope substitution and absent identity/binder controls | PASS |
| 4. Published content immutable | UPDATE/DELETE across ten graph-content tables, new-content insertion, relation moves, lifecycle reparent/reset, competency edits and stable history after source invalidation | PASS |

Concurrency evidence contains 15 publication-versus-content/competency edit
races plus three ordering/identity controls. Tests observe `pg_blocking_pids`
and the actual parent blocker; immutable edits fail `42501` after publication.
Draft writes and new revisions remain positive controls. Learning bindings
reference canonical document/version/span IDs; they do not copy normative
source text into a second authoritative store.

Two additional native migration tests use isolated owner-managed schemas:
populated 0025-to-head upgrade refuses `DENIED_RETIREMENT_UNPROVEN`, and orphaned
lifecycle state refuses `LEARNING_HISTORY_REQUIRES_RECONCILIATION`. Both preserve
the prior revision and relevant rows; neither fabricates publication history.
They are migration safety evidence, not part of the 91 unprivileged-runtime
nodes or permission to migrate real populated data.

The 64-node competency module contains only 21 PostgreSQL nodes; the other 43
are SQLite/migration controls. Domain and SQLite repository/source-authorization
tests are supplementary and must not be counted as native PostgreSQL proof.
Phase-03 issue closure still requires accepted phase 02 and a fresh independent
audit of the integrated candidate; the prior artifact does not establish that
dependency or authorize a merge.

## Full-suite skipped denominator

Exactly seven baseline nodes skipped; none is a phase-02/03 native control.

| Test module (one skipped node each) | Recorded reason |
|---|---|
| `test_admission_subject_share` | `var/load-probe.json` absent |
| `test_branch_integration` | Canonical local integration branches absent in CI checkout |
| `test_canonical_declaration` | Detached CI checkout has no named local canonical branch |
| `test_corpus_snapshot_contract` | SQLite-only epoch trigger definition |
| `test_evidence_provenance` | Eval/mutation/migration/scale artifacts absent in this job |
| `test_forge_roles` | Declared local forge remotes absent |
| `test_tevv_admissibility` | `var/eval-report.json` produced by a separate job |

## Admission handoff

Preserve the nine new cases if hosted execution fails; investigate the observed
cause before changing a runtime boundary. Admit the phase-02 candidate only after
phase 01 is accepted, the expanded native gate reports 138/138 with zero skips,
the full exact-candidate required checks pass, and an independent auditor binds
the downloaded evidence to the actual tested tree. Then reassess #25/#31 and
the #100 dependency separately. Real-data migration, corpus recovery and
production deployment remain outside this test-only change.
