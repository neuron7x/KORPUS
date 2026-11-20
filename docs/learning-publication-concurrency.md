# Publication and graph-edit ordering

Publication must validate one committed learning graph and keep its history immutable.
The lifecycle row is the serialization point shared by publication and graph edits.
This contract uses neutral public-library fixtures and does not authorize deployment.

## The concurrency defect

An ordinary PostgreSQL `READ COMMITTED` query in a trigger can observe the committed
`draft` lifecycle while another transaction holds an uncommitted transition to
`published`. The publication update and a competency edit write different rows.
A plain immutable-state check therefore permits an edit to commit after publication.
Putting both operations in transactions does not itself order them.

The earlier competency guard closes sequential edits of published history. The
forward `0027_learning_competency_integrity` migration additionally replaces the
existing content and course-identity guard bodies with locking reads. Pre-existing
migrations `0016` through `0026` remain unchanged.

## Lock protocol

- `publish_version` obtains `FOR UPDATE` on the lifecycle before loading the graph,
  loading bound source states, or validating publication. Trusted identity binding
  remains at the start of the transaction.
- The database guard on course-version `INSERT` and `UPDATE` first takes `FOR SHARE`
  on both OLD and NEW course identities in course-ID order, before lifecycle locks.
  This also covers the first version, when no lifecycle yet exists, and direct SQL
  that bypasses `create_version`. The ordinary foreign-key `KEY SHARE` lock would
  permit a concurrent non-key course-title update to remain uncommitted.
- Content `INSERT`, `UPDATE`, and `DELETE` guard the existing lifecycle rows of both
  OLD and NEW version identities. They take `FOR SHARE` in version-ID order, including
  draft rows, and reject a returned immutable state. Course-identity edits lock the
  lifecycle rows of their existing versions in the same order.
- Direct SQL publication already owns the lifecycle row for its update before its
  structural row triggers execute. Content guards now conflict with that lock too.
- A content editor that owns the shared lock commits first, after which repository
  publication loads the committed graph. A publisher that owns the exclusive lock
  commits first, after which the editor sees `published` and receives SQLSTATE `42501`.

Filtering the locking query to immutable states would skip the crucial draft row.
`FOR KEY SHARE` would also be insufficient: it does not conflict with an update of
the non-key lifecycle state.

## Creation and failure behavior

The repository inserts a course-version row before its lifecycle exists, then inserts
the draft lifecycle before all child content, in one transaction. The guard therefore
allows that first version insert when no lifecycle row exists to lock, while holding
the existing course identity with `FOR SHARE`. It does not
invent a lifecycle, reconstruct historical review, or add missing-row upgrade authority.
The existing atomic draft-deletion path also removes its lifecycle before cascading
the course-version deletion; the same missing-row behavior preserves that cleanup.
Course-version `DELETE` keeps its lifecycle guard without adding a course lock: it
cannot introduce a course association, and acquiring course after the cleanup already
owns lifecycle would add an unnecessary inverse acquisition order.
Migration admission still refuses orphaned competency history and populated deployments
without the existing independent retirement proof.

OLD/NEW locks use a stable order to avoid inversion during relation reassignment. This
does not promise deadlock freedom for every multi-row transaction: DML and foreign-key
checks can hold other row locks first. PostgreSQL deadlock or lock-timeout failures must
abort the transaction; they are not converted into successful publication or editing.
No grants, RLS rules, statement limits, or module ceilings are widened.

The lock protocol protects edits against an existing lifecycle. It does not add a new
constraint requiring a lifecycle to exist at every intermediate SQL statement, and it
does not replace the existing atomic course-creation and migration-admission contracts.

## Native acceptance

`apps/api/tests/test_postgres_learning_concurrency.py` uses the migrated PostgreSQL
application fixture. The fixture verifies PostgreSQL 17 and a separate non-owner
application login. Each actor also verifies effective `read committed` isolation.

The publication-first cases hold a real publication update open while a second
connection attempts valid draft DML. Cases cover every existing learning-content
table and competency insertion, update, deletion, and movement in both directions.
The test queries `pg_blocking_pids` from the lock-owning connection and requires its
own PID to be the actual blocker. After publication commits, the competing operation
must refuse with `42501` and the complete graphs and course identity must be unchanged.

The content-first case holds a real competency edit open while the second connection
calls `publish_version`. It proves that publication waits before reading the graph,
then checks that the real reader observed the graph committed by the editor and that
the published result remains immutable. The reader observer delegates to the actual
reader; it supplies no synthetic rows or validation outcome.

Two first-version cases hold a course-title update while there are no versions or
lifecycles. A second application connection attempts either real `create_version` or
a direct SQL course-version insert. Both must report the course editor as their actual
blocker. After the editor commits, creation can finish. The direct SQL probe rolls back
its deliberately incomplete insert, then the repository creates the complete graph.
Both cases publish with the trusted fixture identity and verify that a later course
title edit receives `42501` without changing the published graph or course identity.

Actor barriers, statement timeouts, bounded server-state polling, and transaction
cleanup bound both cases. The polling delay is not evidence of a lock. A competing
operation completing before the lock owner commits is an assertion failure.

These tests must run on PostgreSQL. Without the required service URLs they are skipped;
SQLite tests, SQL compilation, test collection, or a static schedule analysis cannot
satisfy native acceptance. A hosted run on the final candidate commit is still required.

## References

- [PostgreSQL 17 transaction isolation](https://www.postgresql.org/docs/17/transaction-iso.html)
- [PostgreSQL 17 explicit locking](https://www.postgresql.org/docs/17/explicit-locking.html)
- Existing parent-lock precedent: `0019_temporal_corpus_snapshot.py`,
  `korpus_refuse_approved_evidence_mutation`.
