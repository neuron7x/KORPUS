# KORPUS Kubernetes production reference

This directory is a fail-closed production topology contract, not a claim that a cluster was deployed.

Before rendering the production overlay:

1. Replace every `registry.invalid/...@sha256:REPLACE_WITH_VERIFIED_DIGEST` with a signed, registry-verified digest.
2. Create `korpus-runtime-secrets` and `korpus-migration-secrets` through an external secrets controller; never commit Secret manifests.
3. Label the managed-services namespace `kubernetes.io/metadata.name=korpus-services` and expose only PostgreSQL, object store, ClamAV, OTLP and the explicit HTTPS egress proxy/approved endpoints.
4. Bind ingress/gateway only to `korpus-web`; do not expose API or worker directly.
5. Run migration, RLS, backup/restore, load, chaos, rollback and external authorization gates before traffic.
