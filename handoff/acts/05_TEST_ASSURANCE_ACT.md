# Act 05 — tests and assurance

## Executed evidence

- Pytest: 172 collected; 171 passed; 1 skipped; zero failures/errors.
- Line coverage: 87.00%.
- Branch coverage: 66.87%.
- Frozen adversarial evaluation: 30/30.
- Citation failures: 0.
- Access leakage failures: 0.
- Determinism failures: 0.
- Selected critical mutants killed: 26/26.
- Migration parity: PASS.
- Local scale probe: 5000 spans, p50 2.315 ms, p95 2.783 ms, top-1 recall 1.0; local synthetic measurement only.
- Operational gate: PASS with `production_authorized=false`.

## What these tests do not prove

They do not prove real-corpus correctness, production PostgreSQL behavior, production capacity, penetration resistance, legal rights, classification, operator readiness or military authorization.

## Mandatory agent rule

Every new behavior must add a plausible failure model and a test that kills it. Coverage increase without a killable invariant is insufficient.
