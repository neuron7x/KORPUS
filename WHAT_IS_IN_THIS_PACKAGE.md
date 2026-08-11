# KORPUS v6.17.0 canonical recovery repository

This is one canonical source repository, not a concatenation of multiple snapshots. It contains the application, web client, infrastructure/deployment definitions, migrations, tests, evaluation and mutation catalogues, assurance tooling, documentation, manifests and Git history.

## Assurance boundary

Local engineering evidence and production authorization are separate predicates. Missing production-like TEVV/load/recovery, real PostgreSQL evidence, complete scanner/container-SBOM evidence, exact-environment reproduction, or independently trusted red-team evidence remains FAIL. No local code change may convert unavailable external evidence into PASS.
