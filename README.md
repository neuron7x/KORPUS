# KORPUS v0.9.7

KORPUS is a bounded-evidence, multi-tenant knowledge/inference system with fail-closed authorization, evidence-bound answers, abstention, auditability and explicit production admission predicates.

**Authoritative start:** `README_FIRST.md`.

| Surface | Current state |
|---|---|
| Behavioral source | `15f1630f4327babeba37802d64b195d43cae256b55042b7f44517a24784a78aa` |
| Regression | 2345/2345 PASS; 1 external PostgreSQL skip |
| Mutation | 349/349 KILLED |
| Web | 146/146 PASS + browser 5/5 |
| Determinism | PASS across 4 hash seeds |
| Operational engineering gate | PASS |
| Hard predicates | 14/14 software-ready; 0/14 external |
| Production authorization | **false** |

Repository roots: `apps/`, `packages/`, `contracts/`, `config/`, `evals/`, `deploy/`, `infra/`, `scripts/`, `docs/`, `handoff/`, `reports/`.
