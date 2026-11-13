# Contract-migration runtime admission

Status: source implementation; existing-database contract upgrades remain blocked.
This is not an N-1 compatibility certificate or production authorization.

Migration `0025_sealed_provenance_integrity` rejects previously possible writes to
sealed records. The expand-only validator must continue rejecting that transition
on an existing installation. Neither its policy nor its baseline hashes are changed.

Every Alembic migration execution passes through `apps/api/migrations/env.py` before DDL.
The active source's immutable baseline bytes and complete single-parent graph are
verified before Alembic imports revision modules. Unknown future files, changed or
missing baseline policy, redirected source, unsupported dialects and offline SQL
have no implicit admission.

The execution paths are:

- Empty database bootstrap: inspect the actual database catalogs on the same
  connection and transaction that will execute the migrations. PostgreSQL user
  schemas, relations, routines and types count as existing state. SQLite main,
  temporary and attached databases are inspected.
- Historical forward migration: current and requested revisions must lie in the
  complete canonical baseline chain, in forward order; every pinned migration
  must match its unchanged SHA-256. This preserves historical transitions such
  as `0023` to `0024` without admitting `0025` on existing state.
- Current-head no-op: the actual revision must be the current known head and the
  installed snapshot/sealing guards must pass semantic validation. A stamped
  revision, missing guard or inert trigger is insufficient.

All other existing-database transitions, including guard-removing downgrades, are
denied. There is no retirement Boolean, test-environment exception, database-name
allowlist, accepted JSON receipt or alternative deployment switch. CLI and
programmatic `stamp` cannot substitute for executing a bootstrap.

SQLite uses `BEGIN IMMEDIATE`; PostgreSQL uses a transaction-scoped advisory lock.
Concurrent cooperating migrators re-observe state after acquiring the lock. This
does not claim exclusion of an arbitrary privileged database administrator.
Historical source migrations run within the same transaction. The runtime image
includes the unchanged baseline policy as a readable artifact.

Alembic `current` and `check` use a separate inspection path, restricted to the
installed Alembic inspection callbacks and a database-enforced read-only mode.
Unknown callbacks cannot enter that path. Inspection grants no migration authority.

Regression evidence covers real Alembic subprocesses and SQLite/PostgreSQL:
bootstrap, canonical no-op, baseline forward migration, unchanged database after
denial, missing/changed baseline proof, unknown future revision, forged head,
missing/inert guards, CLI/programmatic stamping, concurrent migrators and removal
of the runtime admission call. Historical tenancy rollback SQL is tested directly
on an isolated fixture; it does not authorize a current deployment downgrade.

An existing installation cannot advance to `0025` until a separate, independently
verified retirement protocol establishes database/source/image identity, drainage
of old API and worker revisions, freshness and serialization. No such evidence is
invented or accepted by this implementation. Deployment remains fail-closed.
