# KORPUS v0.9.7 — Operator Runbook

## Verify extracted repository
```bash
PYTHONPATH=apps/api/src:scripts python3 scripts/verify_source_manifest.py
PYTHONPATH=apps/api/src:scripts python3 scripts/verify_current_truth.py --root .
PYTHONPATH=apps/api/src:scripts python3 scripts/check_release_identity.py
PYTHONPATH=apps/api/src:scripts python3 scripts/validate_repository.py --context FULL_SSOT_DISTRIBUTION
```

## Behavioral freeze rule
Current behavioral source digest: `15f1630f4327babeba37802d64b195d43cae256b55042b7f44517a24784a78aa`.

Any change under `apps/api`, `apps/web`, `contracts`, `scripts`, `config`, `evals`, `deploy`, `infra` or CI/release orchestration invalidates source-bound regression/mutation/eval evidence until it is regenerated.

## Local topology
Use `docker-compose.yml` for local dependencies. Local SQLite/synthetic results are not production PostgreSQL/SLO evidence.

## Production rule
Never manually set or describe `production_authorized=true`. Final authorization is produced only after every mandatory external predicate is admissibly satisfied.

## Recovery
Use `docs/runbooks/OPERATIONS.md`, `INCIDENT_RESPONSE.md`, `BACKUP_RESTORE.md`. A real recovery attestation still requires an external/live environment drill.
