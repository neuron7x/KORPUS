# ACT-002 — Structural Defragmentation Report

## Identity

- Target release identity: `v6.3.0`
- Base source HEAD: `d9c59d3e888b1191690a3229f9fb13558a455d25`
- Execution mode: single implementation agent in isolated branch `act-002-defragment`
- Promotion status: `NOT_READY_FOR_PROMOTION`

This report describes structural changes only. It does not claim independent verification. The repository contract requires implementation and independent verification to remain separate roles.

## Mission

Reduce structural fragmentation while preserving KORPUS trust semantics, public API behavior, database meaning, evidence authority, access-before-retrieval, claim/citation binding, abstention, subscription intersection semantics, conversation ownership, model-egress restrictions and audit atomicity.

No product feature, payment provider, corpus payload or production authorization was added by this act.

## Verified structural delta

| Surface | Before | After | Result |
|---|---:|---:|---|
| `api/routes.py` | 864 LOC | 17 LOC | aggregator only; bounded route modules |
| `application/answer_query.py` | 830 LOC | 580 LOC | orchestration spine retained; pure analysis/audit extracted |
| `config.py` | 583 LOC | 423 LOC | schema boundary retained; cross-field policy extracted |
| `web/public/app.js` | 683 LOC | 381 LOC | bounded reader modules |
| `web/public/console.js` | 644 LOC | 307 LOC | bounded operator capability modules |
| internal import cycles | 3 SCCs | 0 SCCs | acyclic internal import graph |
| CSS palette roots | 2 | 1 | one token SSOT |

LOC is a structural diagnostic only; it is not used as a quality or value metric.

## A — Release identity SSOT

### Old responsibility
Current release identity was independently repeated across ZIP naming, Python package metadata, web package metadata, README, desired-state generation and assurance tooling. The delivered archive name claimed `v6.3.0` while Git only described `v6.1.0-4-gd9c59d3`.

### New responsibility
`apps/api/src/korpus/release.json` is the machine-readable current release identity. Python and release tooling load it through `release.py` / `scripts/release_identity.py`.

`check_release_identity.py` verifies parity across current active surfaces. A second `--require-git-tag` gate is reserved for formal promotion.

### Invariant
Current release surfaces cannot silently disagree. Historical documents retain historical identifiers.

### Evidence
Current parity check: PASS for version `6.3.0` / tag declaration `v6.3.0`. The Git tag is intentionally not created because the formal promotion gates are not all current.

## B — Source manifest vs distribution manifest

### Old responsibility
`REPOSITORY_MANIFEST.json` conflated committed source with package-only evidence objects. It declared 580 files while the delivered Git source contained 550 tracked files.

### New responsibility
Two explicit schemas exist:

- `korpus.source-manifest.v1` — committed source snapshot;
- `korpus.distribution-manifest.v1` — exact final archive contents.

`verify_source_manifest.py` verifies source parity. `verify_package.py` verifies the archive against its distribution manifest including path set, byte size and SHA-256.

### Invariant
A source manifest never claims generated package-only files. A distribution manifest never masquerades as a source manifest.

## C — Documentation convergence

`docs/architecture/SYSTEM.md` is the current architecture SSOT. Versioned SYSTEM_V2…V5 documents are explicitly historical. Active README and product documents now point to the current architecture and current product objective.

Current product scope is:

1. authenticated account;
2. subscription-gated access;
3. evidence-bound Q&A;
4. controlled corpus/operator administration.

Instructor workspace, curriculum/quiz generation, administrative-document generation, voice/photo input and native mobile applications are deferred capabilities rather than current MVP acceptance criteria.

## D — Internal dependency graph

The following cycles were removed:

- `config ↔ controlled_requirements`;
- `application.deployment ↔ kubernetes_requirements`;
- `infrastructure.repository ↔ infrastructure.ingestion_jobs`.

The ingestion table declaration now lives behind a shared schema boundary instead of depending on a repository adapter.

`check_import_cycles.py` computes the full internal import graph with Tarjan SCC detection and has a negative-control test proving a synthetic cycle is rejected.

Current result: `cycles=[]`.

## E — API route decomposition

The former monolithic router was decomposed into:

- `routes_health.py`;
- `routes_auth.py`;
- `routes_corpus.py`;
- `routes_review.py`;
- `routes_answers.py`;
- `routes_audit.py`;

`routes.py` remains the small composition point.

A regression in the first split omitted the review router. Existing tests detected the resulting 404; the router was restored before candidate packaging. This failure is retained here as evidence that the tests are capable of killing a real wiring defect.

No endpoint is intentionally removed or renamed.

## F — Answer pipeline decomposition

`ExtractiveAnswerService.execute` remains an explicit top-to-bottom trust orchestration spine.

Pure or side-effect-isolated responsibilities were extracted into:

- `answer_analysis.py`;
- `answer_audit.py`.

The following remain explicit in orchestration order: authorization, planning, bounded retrieval, evidence admission, contradiction handling, abstention and audit persistence.

The refactor does not make conversation history an evidence authority and does not add a generative fallback.

## G — Configuration policy decomposition

`Settings` remains the external schema/configuration entry boundary. Independent cross-field validation groups moved to `config_policy.py`.

Environment variable names and configuration field names were not intentionally changed. Failure-order semantics that are contractual remain covered by regression tests.

## H — Frontend structural defragmentation

No premium redesign or framework migration was performed.

Changes:

- one authoritative CSS token/palette root;
- operator-console CSS separated into `console.css`;
- reader logic split into declaration, corpus, verdict and conversation modules;
- operator logic split into account, mutation and read-only capability modules;
- `api.js` remains the HTTP transport boundary;
- web package now explicitly declares ESM;
- service-worker validation recursively covers the reader import graph;
- console security scanning covers new capability modules.

The console remains intentionally outside offline caching.

## I — High-risk modules deliberately not rewritten

`infrastructure/extraction.py` was not structurally rewritten. Its prior measured coverage is materially below the repository aggregate and ACT-002 requires characterization before parser/OCR refactoring.

`infrastructure/repository.py` was not mechanically decomposed further because it contains deliberate atomic transaction boundaries.

Browser OIDC semantics were not replaced.

## J — Current executable evidence

### Backend targeted regression

Three non-overlapping targeted suites executed against the modified source:

- core API/trust/manifest/tenancy suite: **91 tests, 91 PASS, 0 failures, 0 errors**;
- auth/config/calibration/egress policy suite: **85 tests, 85 PASS, 0 failures, 0 errors**;
- ingestion/reliability/schema/migration/architecture suite: **69 tests, 69 PASS, 0 failures, 0 errors**.

Total current targeted evidence: **245 tests, 245 PASS, 0 failures, 0 errors**.

These are current ACT-002 measurements. They are not a substitute for the full release suite.

### Frontend

Current modified source:

- **112/112 tests PASS**;
- lint PASS;
- typecheck gate PASS;
- production build PASS;
- syntax validation covers 16 modules;
- contrast validation covers 3 surfaces;
- accessibility static validation covers 2 pages.

### Structural/operational validators

Current modified source:

- internal import cycles: PASS, zero cycles;
- module budget: PASS, 170 modules, zero unbudgeted modules, zero violations;
- release identity parity (pre-tag): PASS;
- repository validator: PASS, 1028 paths, 103 requirements, 99/99 audit findings classified;
- infrastructure validator: PASS;
- Kubernetes topology validator: PASS for base and production overlay, 19 resources each; static topology only;
- doctrine catalog validator: PASS — 54 sources, 52 ingestible, 17 second-source quarantine cases, 2 blocked;
- desired-state check: PASS — 20 records.

## K — Evidence explicitly NOT claimed for modified HEAD

The full source-bound assurance reports shipped in the input package describe the pre-ACT source tree. They recorded 1273 backend tests, coverage, mutation testing and reference evaluation for that earlier tree. They are retained as historical evidence only and are not promoted as evidence for the modified candidate.

A broad current backend test execution excluding the OpenAPI contract progressed without an observed assertion failure but exceeded the execution window. It is therefore `INCOMPLETE`, not PASS.

The local Python environment has FastAPI/Starlette versions different from the repository lock. The generated OpenAPI under that local environment differs from the committed contract in framework-produced binary-file schema encoding. The locked-environment OpenAPI gate is therefore `UNEXECUTED/UNKNOWN` for ACT-002 rather than silently regenerating the contract with the wrong framework version.

Formal research assurance, full mutation rerun, current full coverage, current reference evaluation and an independent verifier remain mandatory before promotion.

## L — Security and data-class impact

- No corpus bytes were added.
- No secrets or credentials were added intentionally.
- No authorization widening was intended.
- No subscription state semantics were intentionally widened.
- Model-egress classification enforcement remains fail-closed.
- Evidence authority and abstention semantics remain unchanged by design and are exercised in the targeted regression suite.

## M — Rollback

This act introduces no database migration and no intentional persistent-data transformation. Rollback is source-level: revert the ACT-002 commit on the isolated branch and rebuild from the prior source HEAD.

Do not roll back individual route/manifest/import changes selectively unless their coupled tests are rerun; the act intentionally changes structural boundaries as one coherent unit.

## N — Remaining debt / promotion blockers

1. Install and execute the exact locked Python dependency set.
2. Run the full backend suite on final committed HEAD.
3. Regenerate and verify the OpenAPI contract in the locked environment.
4. Run current coverage and prove no unjustified regression.
5. Run the full mutation catalogue on final HEAD.
6. Run current reference/evaluation suites.
7. Regenerate source-bound assurance snapshot for the exact final HEAD.
8. Obtain independent verification under the repository role-separation contract.
9. Only then create the `v6.3.0` Git tag and formal promoted package.
10. External production debts and `production_authorized=false` remain outside this structural act.

## Eval gate

**ACT-002 structural refactor: PASS_WITH_CAVEATS.**

**Formal release promotion: NOT_READY_FOR_PROMOTION.**

The structural objectives are implemented and targeted tests/validators pass, but full locked-environment release assurance and independent verification are not current for this modified source tree.
