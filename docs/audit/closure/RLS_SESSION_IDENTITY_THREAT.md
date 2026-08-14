# PostgreSQL RLS authorization-identity boundary

Status: STATIC MITIGATION IMPLEMENTED — EXECUTION EVIDENCE NOT AVAILABLE

## Threat

The legacy PostgreSQL path authorized RLS from transaction-local custom settings such as
`korpus.roles`, `korpus.clearance`, `korpus.corpora`, `korpus.classifications`, and
`korpus.compartments`. SQL available to the ordinary application credential can set custom
configuration values, so those settings could not establish an independent database security
boundary against arbitrary SQL under that credential.

## Required invariant

`RLS_claims_used_for_authorization cannot be increased by SQL available to the ordinary application login`

The same condition applies independently to the review credential.

## Selected mechanism

Migrations `0018_nonforgeable_rls_identity` and `0019_rls_binding_backend_identity` move the RLS
trust source to `korpus_rls_identity_bindings` and SECURITY DEFINER accessors. The ordinary app
and review logins cannot read or write that table and cannot execute the binding function.

A distinct `korpus_identity` broker login is the only runtime login granted EXECUTE on
`korpus_bind_rls_identity(...)`. A binding is keyed to and validated against:

- PostgreSQL backend PID;
- backend start timestamp, preventing PID-reuse aliasing;
- `pg_current_xact_id()` xid8 identity;
- target `session_user`, preventing login substitution.

The binder verifies that the target is a live connection to the current database, is neither
SUPERUSER nor BYPASSRLS, and belongs to the app or review runtime role. Conflicting claims cannot
replace an existing exact transaction binding. Bindings are not age-expired while the transaction
is live; stale rows are rendered unusable by the backend-incarnation/xid/login key and are removed
when the PID is subsequently bound to a different transaction/incarnation/login.

Missing binding state fails closed: clearance resolves to `-1`, and corpus/classification/
compartment/role accessors resolve to empty arrays. PostgreSQL repository construction also fails
when the broker URL is absent.

`SqlRepository` no longer contains a PostgreSQL session-GUC identity fallback. Its base
`_apply_postgres_identity()` refuses PostgreSQL use; the PostgreSQL authorization path must use
`RlsBoundSqlRepository`.

## Credential separation

`prepare_postgres_role.py` provisions distinct `korpus_app`, `korpus_review`, and
`korpus_identity` logins plus NOLOGIN runtime membership roles. All runtime logins are
NOSUPERUSER/NOBYPASSRLS. Cross-role membership is revoked. The broker receives only EXECUTE on the
binding function; the binding table remains inaccessible directly.

No privileged credential is stored in source or binding rows. Operational deployment must keep
the broker credential outside any arbitrary-SQL surface exposed through the ordinary app/review
credential. This mechanism contains arbitrary SQL under those database credentials; it does not
claim containment of full process-memory compromise that can steal every configured secret.

## Deterministic destruction controls authored

The PostgreSQL suite now includes controls that:

1. prove app SQL cannot read the binding table, assume the broker role, or call the binder;
2. independently forge legacy clearance, corpus, classification, compartment, and role GUCs;
3. retry protected reads after every independent claim forgery;
4. retry UPDATE, DELETE, and INSERT after forged admin/curator roles;
5. repeat the authorization attack through the review credential;
6. prove a committed binding does not leak into the next pooled transaction;
7. reject target backend-start and login mismatches;
8. reject conflicting claims for the same transaction;
9. backdate `bound_at` and prove age cannot reopen the same transaction for stronger claims;
10. pin constructor rejection for absent broker, reused protected login, and wrong database target;
11. pin the absence of a base `SqlRepository` PostgreSQL identity fallback;
12. retain normal integration, approval-provenance, temporal-race, and epoch-privilege flows through
    `RlsBoundSqlRepository` as positive controls.

## Current evidence boundary

The implementation and tests above are source-defined. They have not produced executable evidence
in the current cycle because GitHub-hosted jobs are not starting under the account billing lock.
A workflow marked failure with no job steps/logs is runner-level non-execution, not a test result.

Therefore none of the following may be claimed yet:

- successful destruction of the arbitrary-SQL attack on real PostgreSQL;
- migration upgrade/downgrade execution correctness;
- full PostgreSQL regression PASS;
- lint/module-budget/assurance PASS for this head;
- production authorization.

## Promotion gate

Required before closure:

1. execute focused broker/RLS destruction controls with the real least-privilege split logins;
2. record exact commands, role identities, row counts, exit codes, and failures;
3. execute the full PostgreSQL suite;
4. execute lint, module-budget, migration, and assurance gates without threshold weakening;
5. retain `production_authorized=false` until every required gate passes.

`STATIC_IMPLEMENTATION=PASS_WITH_CAVEATS`
`EXECUTABLE_EVIDENCE=NOT_EXECUTED`
`MERGE_GATE=FAIL`
`PRODUCTION_GATE=FAIL`
