# KORPUS v6.7.1 canonical assurance-hardened repository

This is one canonical source repository, not a concatenation of two trees. It contains the
application, web client, infrastructure/deployment definitions, migrations, tests, evaluation,
mutation catalogue, assurance tooling, documentation, manifests and Git-history release path.

## Current assurance boundary

Local engineering and adversarial evidence is generated repository-native. Production promotion is
fail-closed and additionally requires production-like TEVV/load/recovery, real PostgreSQL runtime
evidence, complete scanner/container SBOM evidence, exact-environment reproduction, and a trusted
independently signed external pentest. Missing external evidence remains FAIL; it is not waived.

A production release is created only through `scripts/package_production_release.sh`, which requires
a current PASS production-assurance report, a release tag at HEAD and an external Ed25519 signing
key. The private key is never packaged.
