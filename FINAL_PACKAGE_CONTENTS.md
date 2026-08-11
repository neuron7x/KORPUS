# KORPUS v6.10.1 — canonical package index

## Primary surfaces

- `apps/api/` — evidence-bound API, domain/application/infrastructure layers, migrations and tests;
- `apps/web/` — responsive web client and generated API/authorization contract;
- `config/`, `contracts/`, `deploy/`, `infra/` — runtime policy and deployment definitions;
- `evals/`, `scripts/`, `reports/` — TEVV, mutation, security, reliability and release assurance;
- `SOURCE_MANIFEST.json` / `DISTRIBUTION_MANIFEST.json` — byte-level source/distribution inventory;
- Git bundle produced during packaging — complete repository history available in the distribution.

Production authorization is not inferred from repository completeness. `reports/PRODUCTION_ASSURANCE_REPORT.json` is the machine gate.
