# Next 10 iterations

Status: **PLANNED — NOT EXECUTED**. Order is dependency-aware; do not parallelize tasks that modify the same trust boundary or migration chain.

## IT-01 · P0 · Live PostgreSQL/pgvector proof

**Objective:** Replace the single PostgreSQL-only skip with reproducible live integration evidence.

**Audit links:** INF-001, IAM-006, INF-005

**Touchpoints:**
- `docker-compose.yml`
- `.gitlab-ci.yml`
- `apps/api/tests/test_postgres_integration.py`
- `scripts/verify_postgres_restore.py`

**Methods/tools:**
- PostgreSQL non-superuser role
- pgvector
- Alembic
- pytest
- encrypted backup/restore drill

**Acceptance predicates:**
- [ ] 0 PostgreSQL integration skips
- [ ] FORCE RLS isolation proven for documents/versions/spans/embeddings
- [ ] backup restores into a new database
- [ ] schema parity and audit head pass

## IT-02 · P0 · Immutable software supply chain

**Objective:** Make every Python, container and CI dependency content-addressed and verifiable.

**Audit links:** SUP-001, SUP-002, SUP-003, SUP-009

**Touchpoints:**
- `apps/api/requirements*.lock`
- `Dockerfiles`
- `.gitlab-ci.yml`
- `reports/SUPPLY_CHAIN_INVENTORY.json`

**Methods/tools:**
- pip-tools/uv hash locks
- OCI digests
- Syft
- Grype/Trivy
- Cosign
- SLSA provenance

**Acceptance predicates:**
- [ ] all Python requirements contain hashes
- [ ] all OCI images use digests
- [ ] SBOM generated and retained
- [ ] signed provenance verifies before promotion
- [ ] license inventory reviewed

## IT-03 · P0 · Real-corpus TEVV and calibration

**Objective:** Replace synthetic-only evidence with blinded, adjudicated corpus-specific evaluation.

**Audit links:** RAG-001, RAG-003, RAG-007, RAG-014, RAG-020

**Touchpoints:**
- `evals/`
- `apps/api/src/korpus/application/tuning.py`
- `apps/api/src/korpus/application/calibration.py`

**Methods/tools:**
- stratified sampling
- double annotation
- adjudication
- inter-annotator agreement
- frozen holdout
- bootstrap confidence intervals

**Acceptance predicates:**
- [ ] >=100 judged ranking queries
- [ ] >=200 accepted-answer calibration samples
- [ ] blind holdout never used for tuning
- [ ] IAA reported
- [ ] profile hashes bind dataset/protocol/code/model
- [ ] hard leakage/citation gates remain zero

## IT-04 · P1 · Ukrainian retrieval and structured evidence

**Objective:** Improve Ukrainian morphology and prove table/number/unit/formula handling.

**Audit links:** RAG-011, RAG-012, RAG-013

**Touchpoints:**
- `apps/api/src/korpus/application/retrieval.py`
- `apps/api/src/korpus/application/evidence.py`
- `apps/api/src/korpus/infrastructure/extraction.py`
- `evals/`

**Methods/tools:**
- Ukrainian analyzer benchmark
- layout-aware extraction
- table cell provenance
- numeric/unit normalization
- property tests

**Acceptance predicates:**
- [ ] domain slices for inflection/abbreviation/table/number/unit/formula
- [ ] claim offsets remain source-bound
- [ ] no regression on frozen 30 cases
- [ ] new critical mutants killed

## IT-05 · P1 · Risk and injection model replacement

**Objective:** Replace regex-only risk and injection classification with measurable layered controls.

**Audit links:** RAG-009, RAG-010, RAG-018

**Touchpoints:**
- `apps/api/src/korpus/application/risk.py`
- `apps/api/src/korpus/application/answer_query.py`
- `evals/`

**Methods/tools:**
- rules + constrained classifier
- prompt/RAG poisoning corpus
- fuzzing
- calibration curves
- false-positive/false-negative slices

**Acceptance predicates:**
- [ ] explicit confusion matrix
- [ ] attack-family coverage
- [ ] abstention calibration
- [ ] no control text reaches instruction channel
- [ ] evasion mutants killed

## IT-06 · P1 · Repository and configuration decomposition

**Objective:** Split god objects without weakening transactions, RLS or audit invariants.

**Audit links:** COD-001, COD-002, COD-003

**Touchpoints:**
- `apps/api/src/korpus/infrastructure/repository.py`
- `apps/api/src/korpus/config.py`

**Methods/tools:**
- ports/adapters decomposition
- transaction façade
- typed configuration sections
- exception taxonomy
- characterization tests

**Acceptance predicates:**
- [ ] repository responsibilities split by bounded capability
- [ ] single transaction boundary preserved
- [ ] no broad exception in critical path without rethrow policy
- [ ] all state-machine/concurrency tests pass

## IT-07 · P1 · Embedding lifecycle and drift

**Objective:** Make embedding synchronization, model migration and rollback explicit and auditable.

**Audit links:** RAG-016, RAG-017, DATA-004

**Touchpoints:**
- `apps/api/src/korpus/infrastructure/semantic.py`
- `apps/api/migrations/`
- `scripts/`
- `reports/`

**Methods/tools:**
- versioned embedding jobs
- dual-index migration
- shadow evaluation
- drift metrics
- reconciliation ledger

**Acceptance predicates:**
- [ ] zero orphan embeddings
- [ ] model/version bound to every vector
- [ ] backfill resume/retry/dead-letter
- [ ] rollback tested
- [ ] drift threshold opens incident and disables semantic weight when violated

## IT-08 · P1 · Retention, deletion and legal hold execution

**Objective:** Convert corpus policy fields into scheduled, reconciled lifecycle operations.

**Audit links:** DATA-001, DATA-004, OPS-003

**Touchpoints:**
- `apps/api/src/korpus/security/corpus_governance.py`
- `apps/api/src/korpus/application/ingestion_jobs.py`
- `scripts/`
- `docs/runbooks/`

**Methods/tools:**
- policy scheduler
- dry-run diff
- WORM-aware deletion
- legal-hold precedence
- reconciliation reports

**Acceptance predicates:**
- [ ] deletion never bypasses legal hold
- [ ] object/DB/index converge
- [ ] signed data-owner manifest
- [ ] evidence retention policy executed and audited

## IT-09 · P1 · SRE capacity, chaos and recovery proof

**Objective:** Turn reference topology into measured service limits and recovery guarantees.

**Audit links:** SRE-001, SRE-002, SRE-004, SRE-005, SRE-007, INF-004, INF-008, INF-011

**Touchpoints:**
- `deploy/kubernetes/`
- `docs/operations/`
- `docs/runbooks/`
- `reports/`

**Methods/tools:**
- k6/Locust
- toxiproxy/chaos testing
- PITR drill
- canary
- rollback rehearsal
- error budgets

**Acceptance predicates:**
- [ ] p50/p95/p99 by workload
- [ ] saturation point measured
- [ ] RTO/RPO measured
- [ ] failure matrix executed
- [ ] rollback and corpus-release rollback demonstrated
- [ ] named on-call owners

## IT-10 · P1 · Independent security and authorization closure

**Objective:** Produce evidence the repository cannot self-issue: independent tests and formal go/no-go.

**Audit links:** GOV-001, GOV-004, GOV-006, INF-003, INF-006, SUP-007

**Touchpoints:**
- `docs/governance/`
- `docs/security/`
- `docs/audit/closure/`

**Methods/tools:**
- external application pentest
- AI/RAG red-team
- parser/container assessment
- threat-model review
- authorization package

**Acceptance predicates:**
- [ ] all applicable P0 closed or formally time-bounded with compensating controls
- [ ] signed residual-risk decision
- [ ] document rights/classification approved
- [ ] production_authorized becomes true only through signed external evidence
