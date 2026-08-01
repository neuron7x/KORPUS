# KORPUS conference vertical-slice verifier index

## Candidate identity

Verify the clean committed `HEAD` of branch `act/08-postgres-compartment-coverage`. Do not
accept reports whose `candidate_commit` differs from `git rev-parse HEAD`. The branch name is
historical; bounded ACT commits 03–11 are independently revertible and listed by `git log`.

## Authoritative executable evidence

| Boundary | Command | Expected ignored artifact |
|---|---|---|
| Static web contract | `npm --prefix apps/web run lint` | command output |
| Browser behavior | `npm --prefix apps/web run test:browser` | `var/web-act/browser-junit.xml` |
| Built web runtime | `scripts/run_web_runtime_gate.sh` | `var/web-act/web-runtime-assurance.json` |
| SQLite API smoke | `KORPUS_LIVE_DATABASE_MODE=sqlite scripts/run_web_api_boundary_gate.sh` | v2 boundary JSON/JUnit |
| PostgreSQL vertical path | `KORPUS_LIVE_DATABASE_MODE=postgres scripts/run_web_api_boundary_gate.sh` | `var/web-act/web-api-live-boundary.json` |
| PostgreSQL RLS/restore | GitLab `api:postgres-and-restore` sequence or an equivalent clean-room execution | `var/act-01/postgres-live-assurance.json`, JUnit, manifest |
| Repository contracts | `PYTHONPATH=apps/api/src make validate` | command output |
| Migration/eval | `make migration-gate eval` | reports under ignored `var/` |
| Type lock | install `apps/api/requirements.dev.lock` into a fresh venv with `--no-deps`, then `pip check` and `mypy apps/api/src` | command output |

## Falsification history

- Obsolete hard-coded restore revision rejected the real current Alembic head.
- `pg_dump --file=-` created a persistent plaintext file literally named `-`; fixed by using
  PostgreSQL's stdout default and a real-semantics test double.
- PostgreSQL CI image lacked Git; evidence provenance now uses validated CI commit input.
- Old assurance JSON is rejected after privilege predicates expand; results are not inherited.
- The prior dev lock could not import mypy because its pinned pathspec violated mypy metadata
  and two mandatory no-deps packages were absent.

## Claims that remain open

- `IAM-006` is `CONFIRMED_OPEN`: arbitrary SQL through `korpus_app` can broaden GUC claims.
- JWT test mode is not production OIDC evidence.
- Local anchored durations are not production SLAs.
- GitLab pipeline and independent clean-room reproduction remain external gates.
- Repository-wide Ruff has pre-existing debt; changed-scope Ruff passes do not erase it.
- `production_authorized=false`; no military, regulatory or deployment authorization is made.

## Independent-verifier acceptance

The verifier must run from a new clone/worktree with new credentials and empty storage, retain
only sanitized JSON/JUnit/manifests, compare every embedded commit to candidate `HEAD`, inspect
cleanup, and report counterexamples. Because the authoring agent changed code, local green
evidence can support only `PASS_WITH_CAVEATS` until that reproduction succeeds.
