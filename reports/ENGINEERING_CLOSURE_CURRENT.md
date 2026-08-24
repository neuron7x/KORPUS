# KORPUS v0.9.7 — Engineering Closure Current

**Date:** 2026-08-23  
**Role:** `ENGINEERING_CLOSURE_CANDIDATE`  
**Behavioral source digest:** `15f1630f4327babeba37802d64b195d43cae256b55042b7f44517a24784a78aa`  
**Production authorization:** **FAIL / false**

## Verified local state

| Surface | Result | Evidence class |
|---|---:|---|
| Full regression | **2345/2345**, 64/64 shards, 0 fail, 0 error, 1 skip | ANCHORED |
| Full mutation | **349/349 KILLED**, 0 survivor/invalid/error | ANCHORED |
| Web Node tests | **146/146 PASS** | ANCHORED |
| Browser E2E | **5/5 PASS** | ANCHORED |
| Determinism | **4 seeds × 66 tests**, identical replay/outcome digests | ANCHORED |
| Release/package/handoff targeted | **47/47 PASS** | ANCHORED |
| Release identity | **11/11 PASS** | ANCHORED |
| Module budget | **456 entries**, ratchet tests PASS | ANCHORED |
| OpenAPI | **31 paths** | ANCHORED inventory |
| GitHub workflows | **10** | ANCHORED inventory |
| Infrastructure static validator | **135 requirements / 0 failures** | LOCAL_STATIC |
| Kubernetes topology | **19 base + 19 production resources / PASS** | LOCAL_STATIC |
| GCP production contract | **72/72 PASS** | LOCAL_STATIC |
| GCP SLO contract | **11/11 PASS** | LOCAL_STATIC |
| Software hard predicates | **14/14 ready** | ANCHORED |
| External hard predicates | **0/14 satisfied** | ANCHORED |

The only regression skip is `test_postgres_migrated_search_rls_access_and_audit`, because `KORPUS_POSTGRES_TEST_URL` is not configured. It remains an external-real-backend blocker, not a local PASS.

## Local empirical evidence

- Synthetic safeguard evaluation: **30/30 PASS**, but **not admissible as production TEVV**. The run is below the configured 200-observation floor and its Wilson 95% interval width is **0.113513**.
- Local SQLite scale probe: 5,000 spans / 80 iterations; p50 **3.520670 ms**; p95 **4.545702 ms**; top-1 recall **1.0**. This is not a production SLA.
- Migration parity: **27/27 tables**, audit head seeded, FTS5 present.
- Operational engineering gate: **PASS**; `production_authorized=false`.

## Closure statement

All locally executable engineering gates required for this freeze have admissible PASS evidence. Remaining launch debt is external evidence: real PostgreSQL/RLS, hosted load/recovery, exact external runtime, trusted scanners/builder/signing, real-domain and independent TEVV/red-team, and HUMAN PEC judgments.
