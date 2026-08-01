# ACT-19 — Seven-iteration retrieval performance assurance

- Issue ID: `KORPUS-ACT-19`.
- Value hypothesis: retrieval latency can be reduced causally by eliminating redundant governed-state materialization while preserving authorization, ranking and cache invalidation semantics.
- Linked findings: local scale-probe performance debt; no external finding is closed.
- Trust boundary: request identity and corpus scope → release fingerprint/cache key → bounded candidate query → deterministic reranker.
- Allowed files: repository retrieval implementation, scale probe, focused retrieval/cache tests, this contract and verifier index.
- Forbidden files: RLS policies, identity semantics, migrations, frozen audit source, production authorization and ranking weights.
- Killable invariants: cache release calculation materializes no evidence models; reranking materializes at most the configured candidate budget; top-1 marker recall remains 1.0; candidate count never exceeds its budget; empty authorization stays empty.
- Adversarial cases: dense 5,000-span query, repeated cache hit, unauthorized corpus intersection, superseded/temporally invalid version and noisy latency outlier.
- Acceptance predicates: focused tests kill reintroduced materialization; repeated anchored probes preserve correctness; median improvements are reported without SLA extrapolation; all applicable regressions remain green.
- Rollback: revert the bounded ACT-19 commit; no schema or data rollback is required.
- Migration/data impact: none.
- Commands executed: cProfile baseline, sparse and dense scale probes, focused repository/retrieval/cache tests, then repository gates recorded below.
- Evidence generated: ignored `var/scale-report.json`, dense probe/profile outputs and command logs; no corpus data or credentials retained.
- Unexecuted gates: independent clean-room verification, GitLab pipeline and production load test.
- Residual uncertainty: SQLite single-process measurements do not predict PostgreSQL network/concurrency performance; author measurements require independent reproduction.

## Seven falsification iterations

1. Baseline: sparse uncached and cached paths measured separately.
2. Profile: cache hits were found to materialize all 5,000 spans through the release fingerprint.
3. Release query: replaced span-model construction with an authorization-equivalent version fingerprint query.
4. Dense workload: exercised the full 256-candidate reranker rather than a one-hit query.
5. Materialization bound: retained the authorization starvation buffer but instantiated no more than 256 candidates.
6. Scoring experiment: one-pass normalization was tested and rejected because end-to-end improvement was not demonstrated.
7. Integrated gate: repeat measurements and regressions bind speed claims to correctness and exact local environment.

## Anchored result and gates

- Baseline commit: `915c33a573a0136c26efc66e8c511d901ccd1df2`; Python 3.12.3; Linux 6.8.0-136-lowlatency x86_64; SQLite FTS5; 5,000 spans.
- Three-run median of per-run p50, sparse: uncached `10.894 ms` → `5.269 ms`; cached `585.554 ms` → `3.612 ms`.
- Three-run median of per-run p50, dense 256-candidate workload: uncached `265.986 ms` → `126.979 ms`; cached `672.633 ms` → `3.297 ms`.
- Correctness: top-1 predicate `1.0` for every baseline/candidate run; candidate bounds `1/256` preserved.
- Passed: 15 focused tests; full API suite (one PostgreSQL environment skip); handoff/repository/infrastructure/Kubernetes validators; changed-scope Ruff; mypy 44 files; migration gate; eval 30/30; mutation 30/30 killed.
- Known gate result: repository-wide Ruff reports 153 pre-existing findings outside this bounded change; changed-scope Ruff passes.
