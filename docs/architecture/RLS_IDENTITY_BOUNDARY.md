# PostgreSQL RLS identity boundary

Status: design contract for issue #31. This document does not claim executable closure.

## Invariant

`RLS authorization claims cannot be increased by SQL available to the ordinary app or review login.`

The old custom `korpus.*` settings are request metadata, not a security boundary: the same login can call `set_config` for those names. RLS therefore must not trust them.

## Threat model

Must contain independently:

- arbitrary SQL executed with the ordinary `korpus_app` credential;
- arbitrary SQL executed with the ordinary `korpus_review` credential;
- forged role, clearance, corpus, classification and compartment settings;
- direct attempts to write/bind trusted authorization context;
- stale pooled connections, backend-PID reuse, retries and rollback;
- missing trusted identity binding.

Explicitly separate: compromise of the dedicated authorization-broker credential or complete API-process compromise. Those are a larger trust boundary and require external isolation/secret-management controls.

## Killed hypothesis: target prepare + opposite confirmation

The prior two-party proposal is rejected before runtime integration.

A target transaction cannot write its pending context row and then have another PostgreSQL connection confirm that row before the target commits. Under PostgreSQL MVCC the uncommitted row is not visible to the confirmer; an update of a previously committed row is also locked by the target transaction. Waiting for confirmation while keeping the target transaction open therefore creates an impossible visibility/locking dependency.

Result: `TWO_PARTY_PREPARE_CONFIRM = KILLED_BY_MVCC` [STATIC].

This is why the authorization context must be committed by a connection that is **not** the protected target transaction.

## Selected mechanism hypothesis: dedicated authorization broker

Introduce a third narrowly privileged PostgreSQL login, `korpus_authz`. It is not a data-plane login and receives no ordinary table DML privileges.

For each protected PostgreSQL transaction:

1. the target app/review connection begins its transaction and reads `pg_backend_pid()`, `txid_current()` and `session_user`;
2. the application already has a validated domain `Identity` from the authentication/entitlement layer;
3. a short independent `korpus_authz` connection calls `korpus_bind_rls_context(pid, txid, login, claims...)`;
4. the SECURITY DEFINER binder verifies that the target PID exists in the same database, the target session login matches, and the supplied transaction id matches the target backend's current xid;
5. the broker commits the context row **before** the target executes protected SQL;
6. RLS helper functions accept no authorization arguments and return claims only for an exact `(backend_pid, txid, session_login)` match;
7. missing or stale context returns denial defaults, never legacy `korpus.*` settings.

The target transaction never writes its own trusted context. Therefore arbitrary SQL using `korpus_app` or `korpus_review` cannot self-promote unless it also compromises the separately authenticated broker boundary.

Context storage is pruned opportunistically for dead backends and is replaced per active backend PID. The 64-bit `txid_current()` identity prevents a committed context from carrying into the next transaction on a pooled connection.

## Required database properties

- `public.korpus_rls_context` is inaccessible directly to `PUBLIC`, `korpus_app`, and `korpus_review`;
- `korpus_bind_rls_context(...)` is executable only by `korpus_authz`;
- RLS accessors are executable by app/review but accept no claims and expose only the current transaction's row;
- binder/accessors use SECURITY DEFINER only for the protected context operation, fixed `search_path=pg_catalog`, and fully-qualified relation names;
- binder verifies target database/login/backend and target xid before writing;
- `korpus_app`, `korpus_review`, and `korpus_authz` remain NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOINHERIT, NOBYPASSRLS;
- app/review cannot `SET ROLE korpus_authz`; broker cannot inherit app/review runtime groups;
- broker has CONNECT + schema USAGE + binder EXECUTE only; no data-plane table DML;
- no RLS policy depends on `current_setting('korpus.*')` after migration;
- no broker password or connection URL is committed to source.

## Runtime requirement

The repository performs target identity discovery + broker bind before the first protected statement in each PostgreSQL transaction. The broker uses a short dedicated connection with `NullPool` (or an equivalently proven isolation) so a protected transaction cannot deadlock waiting for a connection from its own saturated application pool.

The broker URL must point to the same PostgreSQL database as app/review, use a login distinct from both, and be mandatory for controlled PostgreSQL deployments. Absence or mismatch is a startup failure, not a fallback to GUC authorization.

## Falsification contract

Before promotion, execute on real non-superuser logins:

1. low identity cannot observe a row hidden only by clearance;
2. forged `korpus.clearance` cannot reveal it;
3. repeat independently for corpus, classification and compartment;
4. low writer cannot mutate a visible row; forged `korpus.roles=admin` cannot change that;
5. direct context-table SELECT/INSERT/UPDATE/DELETE fails for app and review;
6. app/review cannot execute the binder;
7. app/review cannot `SET ROLE korpus_authz`;
8. broker cannot perform ordinary document/evidence DML;
9. binder rejects wrong target login, wrong database, missing backend and wrong xid;
10. stale context from a prior transaction fails closed;
11. missing context fails closed;
12. legitimate app operations succeed after broker binding;
13. legitimate review transitions succeed after broker binding;
14. forged legacy `korpus.*` settings are semantically irrelevant to every protected RLS policy;
15. SQLite remains application-filtered and does not pretend to provide this PostgreSQL boundary.

The source-defined tests in `test_postgres_rls_claim_forgery.py` establish the primary role/clearance/corpus/classification/compartment destruction contract. Protocol tests must additionally cover broker privilege minimization, binder target verification, stale/missing context and legitimate app/review paths.

## Promotion rule

`STATIC_DESIGN != EXECUTABLE_EVIDENCE`.

Production remains blocked until migration, provisioning, runtime binding, deterministic destruction tests, full PostgreSQL suite, migration upgrade/downgrade, lint/module-budget and assurance gates execute with exact commands and exit codes.