# ACT-25 — Trusted authorization plane

## Value hypothesis

Replacing application-controlled PostgreSQL session claims with independently signed,
single-transaction capabilities removes the confirmed IAM-006 privilege-broadening path
without expanding the product surface.

## Linked finding

- `IAM-006` — application-controlled session GUC values can broaden effective RLS claims.

## Trust boundaries

- independent capability issuer → PostgreSQL authorization schema;
- PostgreSQL application role → governed corpus tables;
- migration owner → capability-key provisioning and revocation.

The issuer and its signing key MUST NOT exist in the API process. This act implements the
database verifier and issuer protocol, not a claim that an external issuer is deployed.

## Allowed files

- the new migration, authorization broker, capability verifier/provider, runtime wiring,
  governed repository/semantic access paths and their focused API tests;
- PostgreSQL role, restore, live-assurance, mutation and repository validators;
- Docker Compose, Kubernetes base manifests and the bounded GitLab live job;
- the threat model, this act and verifier index.

## Forbidden files and changes

- `docs/audit/source/**`;
- production keys or credentials;
- weaker RLS, superuser/BYPASSRLS/table ownership for the application role;
- an issuer embedded in the API runtime;
- PASS when live PostgreSQL or an independent issuer was not exercised.

## Killable invariants

1. Raw `korpus.*` GUC manipulation never authorizes a governed row.
2. A missing, malformed, tampered, expired, not-yet-valid, wrong-audience or unknown-key
   capability fails closed.
3. A capability is bound to exactly one database transaction; replay in another transaction
   fails.
4. Corpus, classification, clearance, compartment, role and operation scope are read only
   from a verified capability.
5. The application role cannot read or mutate signing keys or replay state.
6. The application role cannot sign, provision or revoke capabilities.
7. Missing context returns zero governed rows.

## Adversarial cases

- direct `set_config` of the former broad claims;
- payload and signature mutation;
- reuse of a valid capability in a second transaction;
- capability for a different corpus or unrelated compartment;
- write attempted with read-only capability;
- direct reads of the private authorization schema.

## Acceptance predicates

- authoritative Alembic head includes the new migration;
- clean PostgreSQL migrates to head;
- pre-fix arbitrary-SQL disclosure is preserved as evidence;
- every killable invariant executes against the non-superuser application role;
- all applicable repository gates pass;
- machine evidence says `production_authorized=false` and at most `PASS_WITH_CAVEATS`;
- independent post-change verification remains required.

## Rollback and migration impact

Downgrade removes capability policies and restores the previous application-controlled GUC
policies. Because that reopens IAM-006, rollback requires taking the application offline or
accepting the explicitly documented security regression. Key and replay tables contain no
corpus data and are dropped on downgrade.

## Commands executed

- inspected Git identity, status, worktrees, Alembic graph, grants, policies and all linked
  runtime paths before editing;
- started `pgvector/pgvector:0.8.5-pg17-trixie` as `korpus-act25-postgres`, reachable only at
  `127.0.0.1:55441`, with task-specific ephemeral credentials;
- migrated clean `korpus_act25`, exercised `0010 -> 0009 -> 0010`, prepared the non-superuser
  role and provisioned an ephemeral verification key;
- executed the pre-fix arbitrary-GUC SQL attack, focused capability tests, encrypted backup,
  manifest verification, restore into `korpus_act25_restore`, and post-restore verification;
- created a second clean `korpus_act25_full`, migrated it from empty state and ran the complete
  live API suite with both admin and application URLs configured;
- ran repository, infrastructure, Kubernetes, handoff, migration, evaluation, OpenAPI, Ruff,
  mypy and focused mutation gates. Exact final-candidate reruns are required after commit.

## Evidence generated

- `var/act-25/database-capability-assurance.json` — ten live predicates, verdict constrained to
  `PASS_WITH_CAVEATS`, `production_authorized=false`;
- `var/act-25/database-capability-junit.xml` — capability gate JUnit;
- `var/act-25/full-api-junit.xml` — `266 passed`, zero skipped/failures/errors on the clean live
  database;
- `var/act-25/backups/` — encrypted task backup and manifest only; transient and uncommitted;
- `var/act-25/backup-path.txt` — local artifact locator without credentials.

## Verified predicates

- legacy application-controlled GUCs disclose zero governed rows;
- missing capability fails closed;
- valid public scope cannot observe restricted identifiers or counts;
- missing or unrelated compartment denies while the exact compartment permits only its row;
- read-only capability cannot update; scoped curator write succeeds;
- signature mutation and cross-transaction replay fail with explicit database errors;
- the application role cannot read key/replay tables or execute the private verifier;
- clean migration, encrypted backup, separate restore, restored head, RLS, audit invariants and
  source/restore digests passed locally;
- the complete live API suite passed: `266 passed`.

## Unexecuted gates

- no independent clean-environment verifier has reproduced the candidate;
- no deployed external OIDC/broker/key-custody system was available; the repository reference
  broker and deployment contracts were tested, not production isolation;
- GitLab pipeline, push, merge request, external penetration test and production load were not
  executed locally.

## Residual uncertainty

`IAM-006` remains open for external closure. The original GUC escalation is causally blocked,
but repository-local tests cannot prove that a deployed API process lacks the signing key or
that broker entitlements and workload credentials are independently administered. Consumed
capability rows also require an operator-owned expiry cleanup policy under sustained load.
`production_authorized` remains false.
