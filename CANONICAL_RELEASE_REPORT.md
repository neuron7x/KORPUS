# KORPUS v0.9.7 — Canonical Release Report

**Role:** FULL_SSOT_CANONICAL engineering-closure/staging candidate  
**Behavioral source:** `15f1630f4327babeba37802d64b195d43cae256b55042b7f44517a24784a78aa`  
**Source manifest root:** `1a2687ea9fc6e54d7f94e8cbf88c67b3f1f2ab45c838c6aeed9916e7271e2c20`  
**Production authorization:** **false**

## Current evidence

- Regression: **2345/2345 PASS**, 64/64 shards, 0 failures/errors, 1 real-PostgreSQL skip.
- Mutation: **349/349 KILLED**, zero survivors/invalid/errors.
- Web: **146/146 PASS**; Browser E2E **5/5 PASS**.
- Determinism: **4 hash seeds × 66 tests**, one outcome digest and one semantic-replay digest.
- Module ratchet: **456 / 0 violations**.
- GitHub workflows: **10 / 0 policy findings**.
- Software hard predicates: **14/14**. External satisfied: **0/14**.
- Portable current evidence: **224 files** under `handoff/evidence/current/`.

## Verdict

Local engineering closure is `PASS_WITH_CAVEATS` with an explicit external boundary.
**Staging handoff is NOT permitted**: `reports/CANONICAL_RELEASE_REPORT.json` — машинний
двійник цього документа і його джерело — каже `staging_ready: false` та
`engineering_release_candidate: false`.

> **ВИПРАВЛЕНО 02.09.2026.** Тут стояло «closure is PASS … Staging handoff is permitted»,
> тоді як JSON тієї самої назви казав `PASS_WITH_CAVEATS` і `staging_ready: false`. Дві
> тотожності одного предмета, і слабша — рукописна — стверджувала дозвіл, якого машина
> не давала. Шукати треба не згоду, а стан РОЗХОДЖЕННЯ; у розходженні хибний той, кого
> ніхто не перераховує. Production authorization is denied until real PostgreSQL/RLS, hosted load/recovery, exact external environment, hosted supply-chain evidence, independent TEVV/red-team and HUMAN PEC evidence satisfy the hard predicates.
