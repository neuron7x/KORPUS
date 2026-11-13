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

Target resolution reads the raw Alembic destination option and the verified AST
graph, without asking Alembic to import revision metadata. The unpinned `0025`
module has a narrow passive initialization grammar: literal constants and metadata,
ordinary zero-argument function definitions, and its three established imports
(`__future__.annotations`, `collections.abc.Sequence`, `alembic.op`). Decorators,
defaults, executable annotations, classes, arbitrary imports, control flow and
other expressions are rejected before execution. This is a restricted grammar,
not a claim that arbitrary Python can be statically proved harmless. Installed
Python/Alembic dependencies remain part of the trusted runtime.

After database admission, the Alembic revision map executes the exact captured
source bytes that passed proof. It does not reread revision files or load `.pyc`
files. A concurrent file replacement or forged cache therefore cannot substitute
different code between source proof and migration execution. Inspection uses the
same captured source only inside its read-only transaction.

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
of the runtime admission call. Import-time DDL/commit witnesses, decorators,
defaults, annotations, classes, import dependencies, source replacement and forged
cached bytecode have negative controls. Historical tenancy rollback SQL is tested directly
on an isolated fixture; it does not authorize a current deployment downgrade.

An existing installation cannot advance to `0025` until a separate, independently
verified retirement protocol establishes database/source/image identity, drainage
of old API and worker revisions, freshness and serialization. No such evidence is
invented or accepted by this implementation. Deployment remains fail-closed.
