# System architecture

The current executable architecture is specified in `SYSTEM_V2.md`.

## Source-of-truth boundaries

- protected GitLab `main`: source code, contracts and migrations;
- SQL database: document metadata, immutable versions, review state, spans, audit chain and anchor outbox;
- content-addressed object store: immutable uploaded bytes;
- search index: derived, rebuildable candidate structure;
- external audit anchor: independently stored checkpoint;
- CI artifacts: tests, evals, mutation, migration, scale, SBOM and build evidence.

Local worktrees and generated indexes are disposable. They are never authoritative state.

## Extraction threshold

The modular monolith remains intentional because authorization, temporal selection, evidence construction and audit share transactional invariants. A service may be extracted only after:

1. a versioned contract exists;
2. deterministic replay exists;
3. failure and rollback semantics are tested;
4. cross-service authorization cannot widen access;
5. measured scale pressure justifies the new failure surface.
