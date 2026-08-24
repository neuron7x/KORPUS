# KORPUS v0.9.7 canonical recovery repository

This archive contains one canonical source tree directly under one versioned top-level directory.
It contains the application, web client, GCP infrastructure-as-code, migrations, tests, evaluation
and mutation catalogues, assurance tooling, documentation and release provenance metadata.
Git history is deliberately absent and no source commit is invented.

`SOURCE_MANIFEST.json` binds the canonical source bytes. `PACKAGE_BUILD.json` binds the gitless
package to that source-manifest root. `DISTRIBUTION_MANIFEST.json` binds the final archive payload.
Historical archive fragments under `LINEAGE/` are provenance-only and are excluded from source truth.

## Assurance boundary

Local engineering evidence and live production authorization are different predicates. Missing
production-like TEVV/load/recovery, live PostgreSQL/scanner evidence, exact hosted execution,
trusted signing/attestation or independent red-team evidence remains fail-closed.
