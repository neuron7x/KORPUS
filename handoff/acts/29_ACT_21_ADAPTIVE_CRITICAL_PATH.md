# ACT-21 — Adaptive retrieval critical path

- Value hypothesis: one immutable character-gram representation reused by scoring and MMR reduces CPU/work amplification without changing ranking semantics.
- Linked findings: retrieval efficiency follow-up; no external finding is closed.
- Trust boundary: authorized bounded candidates → deterministic component scoring → MMR selection.
- Allowed files: retrieval implementation/properties, scale evidence, mutation harness if needed, this act and verifier index.
- Forbidden files: access/RLS policy, ranking weights, calibration labels, migrations and production authorization.
- Killable invariants: precomputed and legacy scores are equal; gram inventory covers every candidate; output order, score and top-1 predicate are unchanged.
- Adversarial cases: incomplete gram inventory, dense 256-candidate query, permutations, irrelevant corpus and repeated stress.
- Acceptance: reduced n-gram construction/CPU or the patch is rejected; focused/full regression, eval and mutation gates remain green.
- Rollback: revert the bounded ACT-21 commit; no state rollback.
- Migration impact: none.
- Residual uncertainty: local SQLite CPU measurements are not production energy or PostgreSQL concurrency evidence.

## Anchored local result

- Environment: Python 3.12.3, Linux 6.8.0-136-lowlatency x86_64, SQLite FTS5, 5,000 spans, 256 candidates and 40 measured iterations per run.
- Three-run median of per-run p50: `163.821 ms` → `152.731 ms` (`6.8%` reduction).
- Three-run median of per-run p95: `218.169 ms` → `193.569 ms` (`11.3%` reduction).
- Profiled n-gram constructions: `6,156` → `3,084` across the same 12-search probe (`49.9%` reduction).
- Profiled scoring + MMR cumulative time: `1.005 s` → `0.570 s` (`43.3%` reduction).
- Correctness: top-1 predicate `1.0` in every baseline/candidate run; 256-candidate bound unchanged.
