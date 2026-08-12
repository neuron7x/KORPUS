# KORPUS v0.1.1 — canonical package index

## Primary surfaces

- `apps/api/` — evidence-bound API, domain/application/infrastructure layers, migrations and tests;
- `apps/web/` — responsive web client and generated API/authorization contract;
- `config/`, `contracts/`, `deploy/`, `infra/` — runtime policy and deployment definitions;
- `evals/`, `scripts/`, `reports/` — TEVV, mutation, security, reliability and release assurance;
- `SOURCE_MANIFEST.json` / `DISTRIBUTION_MANIFEST.json` — byte-level source/distribution inventory;
- Git bundle produced during packaging — complete repository history available in the distribution.

Production authorization is not inferred from repository completeness. `reports/PRODUCTION_ASSURANCE_REPORT.json` is the machine gate.

## GitHub primary transport

- `.github/workflows/` — SHA-pinned CI, assurance, dependency-review and tag-attestation workflows;
- `.github/dependabot.yml` — bounded dependency-update intake;
- `GITHUB_IMPORT.md` — history-preserving import procedure;
- `docs/operations/GITHUB_REPOSITORY_POLICY.md` — external branch/security settings that cannot be proven from source alone;
- `scripts/validate_github_actions.py` — executable workflow hardening predicate with negative controls.
