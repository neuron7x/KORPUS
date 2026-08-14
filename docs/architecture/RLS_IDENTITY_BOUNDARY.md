# PostgreSQL RLS identity boundary

Status: design contract for issue #31. This document does not claim executable closure.

## Invariant

`RLS authorization claims cannot be increased by SQL available to the ordinary app or review login.`

The current custom `korpus.*` settings are request metadata, not a security boundary: both the repository and arbitrary SQL under the same login can call `set_config` for those names. RLS therefore must stop trusting caller-writable session claims directly.

## Threat model

Must contain:

- arbitrary SQL executed with the ordinary `korpus_app` credential;
- arbitrary SQL executed with the `korpus_review` credential;
- forged role, clearance, corpus, classification and compartment session settings;
- stale pooled connections and backend-PID reuse;
- transaction retries and rollback;
- missing trusted identity binding.

Explicitly separate: complete compromise of the API process and every credential mounted into that process. That larger boundary requires a separate external authorization broker/service and is not closed by database RLS alone.

## Selected mechanism hypothesis: broker-bound transaction context

Use a third database identity, `korpus_authz`, as a narrowly scoped authorization-context broker. The ordinary app and review logins never receive privileges that let them create, update or delete trusted authorization context and cannot `SET ROLE` into the broker.

For each protected PostgreSQL transaction:

1. the target app/review connection begins its transaction;
2. it obtains `pg_backend_pid()`, `txid_current()` and `session_user`;
3. the API asks the dedicated broker connection to bind the already-validated application `Identity` to exactly `(database, backend_pid, txid, session_user)`;
4. the broker writes/upserts one protected context row keyed by backend PID, replacing any stale row for that backend;
5. RLS helper functions read only the row whose backend PID, transaction id and login match the currently executing backend;
6. no matching row means denial, never fallback to `korpus.*` settings.

The context table is bounded by active/recent backend count rather than request count because one row is replaced per backend PID. Transaction id prevents stale context reuse after rollback, connection pooling or PID reuse.

## Required database properties

- context table inaccessible to `PUBLIC`, `korpus_app`, and `korpus_review`;
- broker login: LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOINHERIT, NOBYPASSRLS;
- app/review cannot inherit or `SET ROLE` to broker;
- broker function verifies target backend exists in the same database and the supplied login equals that backend's session user;
- RLS accessors are `SECURITY DEFINER` only where needed to read the protected context table, with fixed safe `search_path` and fully qualified relation names;
- accessors accept no authorization arguments; they derive backend PID, transaction id and session user internally;
- no direct policy dependency on `current_setting('korpus.*')` remains after migration;
- no secret, privileged password or capability token is stored in source, package, schema literals, or authorization rows.

## Why this is stronger than signed custom settings

A shared HMAC secret inside PostgreSQL would become a database secret-management problem. A shared HMAC secret in the app process would not protect against full API-process compromise. Public-key JWT verification in PostgreSQL would add a new cryptographic dependency and a second token-verification implementation. Broker-bound transaction context uses PostgreSQL's existing authenticated connection boundary and preserves one application entitlement implementation.

## Falsification contract

Before promotion, execute on real non-superuser logins:

1. low identity cannot observe one row hidden only by clearance;
2. `set_config('korpus.clearance', ...)` cannot reveal it;
3. repeat independently for corpus, classification and compartment;
4. low writer cannot mutate a visible row; forged `korpus.roles=admin` cannot change that;
5. direct DML on the trusted context table fails for app and review;
6. app/review `SET ROLE korpus_authz` fails;
7. stale context with wrong txid fails closed;
8. wrong backend PID fails closed;
9. wrong session user fails closed;
10. missing broker binding fails closed;
11. legitimate app and review operations succeed after broker binding;
12. SQLite behavior remains application-filtered and does not pretend to provide this PostgreSQL boundary.

The source-defined tests in `test_postgres_rls_claim_forgery.py` are the pre-fix destruction contract. On the current implementation they are expected to expose the vulnerability once a runner executes; no pre-fix execution is claimed yet.

## Promotion rule

`STATIC_DESIGN != EXECUTABLE_EVIDENCE`.

Production remains blocked until the migration, provisioning, runtime binding, destruction tests, full PostgreSQL suite, migration upgrade/downgrade, lint/module-budget and assurance gates execute with exact commands and exit codes.
