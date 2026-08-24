# KORPUS v0.9.7 — canonical package index

## Source surfaces

- `apps/api/` — evidence-bound API, domain/application/infrastructure layers, migrations and tests;
- `apps/web/` — responsive web client and generated API/authorization contract;
- `config/`, `contracts/`, `deploy/`, `infra/` — policy and deployment definitions;
- `evals/`, `scripts/`, `reports/` — TEVV, mutation, security, reliability and release assurance;
- `SOURCE_MANIFEST.json` — byte-level canonical source inventory;
- `PACKAGE_BUILD.json` — gitless package/source binding; no synthetic commit id is permitted.

## Distribution envelope

The canonical outer ZIP is `KORPUS_v0.9.7_PRODUCTION_ASSURANCE_HARDENED_FULL_SSOT_CANONICAL_2026-08-23.zip`.
It has one canonical top-level directory with the source and evidence directly beneath it. Historical
lineage bytes, when present, remain isolated under `LINEAGE/`; they are not executable source.
`DISTRIBUTION_MANIFEST.json` inventories every deliverable file except itself.

## Promotion boundary

Local tests, IaC predicates and package integrity do not imply live production authorization.
Credential-bound GCP execution, production-like load/recovery, live scanner/PostgreSQL evidence and
independent TEVV/red-team evidence remain separate fail-closed predicates.
