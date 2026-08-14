# PostgreSQL RLS session-identity threat boundary

Status: STATIC SECURITY FINDING — NOT EXECUTED

## Finding

KORPUS PostgreSQL row-level policies consume authorization claims from custom session settings such as `korpus.roles`, `korpus.clearance`, `korpus.corpora`, `korpus.classifications`, and `korpus.compartments`.

The application repository itself writes those values with `set_config(..., true)` before queries. PostgreSQL accepts arbitrary two-part custom option names as placeholder settings. Therefore the ordinary database login that can execute arbitrary SQL can also attempt to replace the same authorization settings that RLS trusts.

## Security consequence

Current RLS is a defense against ordinary application-query mistakes only if the application is the sole trusted writer of the session claims. It is not yet proven to be an independent authorization boundary against arbitrary SQL executed with the application credential.

Do not describe PostgreSQL RLS as independently containing SQL injection / arbitrary-SQL compromise until a deterministic non-superuser destruction control proves the session identity cannot be forged.

## Required invariant

`database authorization claims consumed by RLS cannot be increased by SQL available to the ordinary application login`

At minimum, a non-superuser `korpus_app` connection must be unable to self-assign an unauthorized role, clearance, corpus, classification, or compartment and then observe/write rows that were previously invisible.

## Required falsification

Using the real least-privilege PostgreSQL app login:

1. establish a restricted row not visible to a low-clearance identity;
2. attempt transaction-local `set_config` / `SET` changes for every RLS claim axis;
3. retry SELECT and each relevant write operation;
4. any newly visible or writable protected row is a hard FAIL;
5. repeat through any review-only connection path separately;
6. retain ordinary authorized application flows as positive controls.

No production authorization may rely on RLS as an independent barrier until this is execution-proven.
