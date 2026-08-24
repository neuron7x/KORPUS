# ACT 05 — Test & Assurance — KORPUS v0.9.7

| Gate | Result |
|---|---:|
| Full regression | 2345/2345 PASS; 1 external PostgreSQL skip |
| Full mutation | 349/349 KILLED |
| Web Node | 146/146 PASS |
| Browser E2E | 5/5 PASS |
| Determinism | 264/264 test executions across 4 seeds |
| Release/package/handoff targeted | 47/47 PASS |
| Operational engineering gate | PASS |

The regression skip remains explicit: `KORPUS_POSTGRES_TEST_URL` is not configured. Local eval 30/30 is not production TEVV; interval width **0.113513** and sample floor requirements are not satisfied.
