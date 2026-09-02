# Verification lattice

A test is valuable only when it kills a plausible defect. KORPUS therefore uses a verification lattice rather than a unit-test-count target.

| Layer | Failure class | Executable evidence |
|---|---|---|
| Contracts | malformed identities, requests, citations, dates | Pydantic/OpenAPI contract tests |
| Pure properties | normalization, bounds, determinism | seeded generative and metamorphic tests |
| State machines | illegal review and version transitions | transition graph and optimistic concurrency tests |
| Noninterference | restricted data changes public behavior | candidate, response and release-hash isolation tests |
| Atomicity | partial document/audit commits | forced-failure rollback tests |
| Concurrency | duplicate approval, split audit order | threaded CAS and total-order tests |
| Adversarial RAG | query/source prompt injection, poisoning | source/query injection cases and abstention gates |
| Temporal | stale, future and superseded authority | as-of version tests |
| Citation | unsupported or shifted quote | exact offsets and SHA-256 quote binding |
| Mutation | tests that pass despite broken predicates | deterministic critical-mutant gate |
| Scenario eval | end-to-end behavior across risk taxonomy | frozen 30-case assurance dataset |
| Migration | drift between runtime metadata and database | clean Alembic upgrade and schema parity gate |
| Scale | accidental O(N) query path | indexed-candidate test and reproducible local probe |
| Deployment | PostgreSQL, identity provider, object storage | environment-specific integration gates |

## Current executable gates

- Every mutant in the hand-designed catalogue must be killed: the gate requires
  `killed == valid_mutants == len(MUTANTS)`, and a second number
  (`mutation_score_over_catalogue`) divides by the WHOLE catalogue so an inapplicable
  mutant shows up in the score itself. The count is deliberately not repeated here —
  it was `11` while the catalogue held several hundred, and a second declaration of a
  growing number drifts again. Source: `scripts/run_mutation_tests.py`, guarded by the
  `mutants` dimension of `config/operations/release-surface.json`.
- Frozen assurance cases must pass with zero access leakage, citation failures, or determinism failures.
- Branch-aware coverage is reported, but never accepted as sufficient evidence.
- Candidate generation must not call the full-corpus listing path.
- Migration from an empty database must match runtime metadata.
- Controlled configuration must reject development identity, auto-created schema, weak keys and unvalidated calibration.

## Dataset discipline

Each frozen case has:

- stable identifier;
- risk category;
- identity and corpus scope;
- query and as-of date;
- expected decision status;
- required or forbidden markers;
- provenance hash.

Synthetic fixtures validate mechanisms. They do not establish real-world accuracy. A production calibration profile requires an independently reviewed corpus-specific dataset and finite-sample risk bound.

## Anti-gaming rules

- No changing expected labels merely to make CI green.
- No aggregate score may hide a hard-constraint failure.
- No test may assert only HTTP 200 for a safety-critical path.
- No mutation is discarded solely because it survives; first determine whether the test or invariant is weak.
- No benchmark result is transferred across hardware, database, corpus, language or workload without a new measurement.
