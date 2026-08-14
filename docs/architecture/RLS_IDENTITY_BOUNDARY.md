# PostgreSQL RLS identity boundary

Status: design contract for issue #31. This document does not claim executable closure.

## Invariant

`RLS authorization claims cannot be increased by SQL available to the ordinary app or review login.`

The old custom `korpus.*` settings are request metadata, not a security boundary: the same login can call `set_config` for those names. RLS therefore must not trust them.

## Threat model

Must contain:

- arbitrary SQL executed with the ordinary `korpus_app` credential;
- arbitrary SQL executed with the `korpus_review` credential;
- forged role, clearance, corpus, classification and compartment session settings;
- direct attempts to write trusted authorization context;
- self-confirmation attempts;
- stale pooled connections, backend-PID reuse, retries and rollback;
- missing trusted identity binding.

Explicitly separate: simultaneous compromise of both database credentials or complete API-process compromise. That larger boundary requires an external authorization broker/service and is not closed by database RLS alone.

## Selected mechanism hypothesis: two-party transaction context

Reuse the already-separated `korpus_app` and `korpus_review` credentials from #25 instead of introducing a third secret.

Every protected transaction uses a prepare/confirm protocol:

1. the target connection calls `korpus_prepare_rls_context(...)` with the already-validated application `Identity`;
2. the SECURITY DEFINER prepare function derives `pg_backend_pid()`, `txid_current()` and `session_user` itself and stores the claims as **unconfirmed**;
3. a short connection authenticated as the opposite database login calls `korpus_confirm_rls_context(pid, txid, login)`;
4. confirmation succeeds only when caller and target belong to opposite runtime groups (`korpus_app_runtime` versus `korpus_review_runtime`);
5. RLS helper functions read a context only when backend PID, transaction id and session login all match the executing transaction and the row is confirmed;
6. missing, stale or newly self-prepared context returns denial defaults, never a weaker fallback.

The context table has one replaceable row per backend PID, so storage is bounded by observed backends rather than request count. Transaction identity prevents a confirmed row from surviving into a later transaction or PID reuse.

### Why target-prepares / opposite-confirms

An app-side SQL injection can call prepare with fabricated admin claims, but that immediately resets its own row to **unconfirmed**. The app login cannot confirm an app target, so the result is denial/DoS rather than privilege escalation. The review surface is symmetric.

Either login may confirm a pending row belonging to the opposite login, but it cannot choose or rewrite that row's claims: those were prepared on the target connection itself. This avoids a shared HMAC secret, persistent capability token, third credential, or duplicate JWT verifier inside PostgreSQL.

## Required database properties

- `public.korpus_rls_context` is inaccessible directly to `PUBLIC`, `korpus_app`, and `korpus_review`;
- prepare/confirm/accessor functions are SECURITY DEFINER only for the minimum protected-table operation, with fixed `search_path=pg_catalog` and fully-qualified context relation;
- prepare derives target PID/txid/login internally and always clears prior confirmation;
- confirm accepts no authorization claims and rejects same-side confirmation;
- accessors accept no authorization arguments and derive current PID/txid/login internally;
- `korpus_app` and `korpus_review` remain NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOINHERIT, NOBYPASSRLS;
- app cannot `SET ROLE` review and review cannot `SET ROLE` app;
- no RLS policy depends on `current_setting('korpus.*')` after migration;
- no persistent secret, password, signing key or capability token is stored in source, package, policy SQL or context rows.

## Runtime requirement

The repository must perform prepare + opposite confirmation before the first protected statement in each transaction. Broker/confirmation connections must not consume the same bounded pool needed by target transactions in a way that can create cross-pool starvation; use short dedicated connections/NullPool or prove equivalent bounded behavior.

## Falsification contract

Before promotion, execute on real non-superuser logins:

1. low identity cannot observe one row hidden only by clearance;
2. forged `korpus.clearance` cannot reveal it;
3. repeat independently for corpus, classification and compartment;
4. low writer cannot mutate a visible row; forged `korpus.roles=admin` cannot change that;
5. direct context-table SELECT/INSERT/UPDATE/DELETE fails for app and review;
6. app cannot confirm its own prepared context; review cannot confirm its own;
7. app cannot `SET ROLE korpus_review`; review cannot `SET ROLE korpus_app`;
8. a newly prepared but unconfirmed stronger context fails closed;
9. stale context with wrong transaction id fails closed;
10. missing context fails closed;
11. legitimate app operations succeed after review-side confirmation;
12. legitimate review transitions succeed after app-side confirmation;
13. forged legacy `korpus.*` settings are semantically irrelevant to every protected RLS policy;
14. SQLite remains application-filtered and does not pretend to provide this PostgreSQL boundary.

The source-defined tests in `test_postgres_rls_claim_forgery.py` establish the primary role/clearance/corpus/classification/compartment destruction contract. Additional protocol tests must cover direct context DML, self-confirmation, stale/unconfirmed state and both legitimate paths.

## Promotion rule

`STATIC_DESIGN != EXECUTABLE_EVIDENCE`.

Production remains blocked until migration, provisioning, runtime binding, deterministic destruction tests, full PostgreSQL suite, migration upgrade/downgrade, lint/module-budget and assurance gates execute with exact commands and exit codes.
