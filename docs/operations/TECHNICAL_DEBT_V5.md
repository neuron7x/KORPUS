# KORPUS v5 — residual debt contract

This document records work that cannot be converted into PASS by local code or synthetic tests.

## Frozen audit debt counts

- 79/99 findings remain non-closed in the frozen audit scope.
- 33 are `MITIGATED_LOCAL`: a material local control exists, but external/live acceptance remains.
- 31 are `EXTERNAL_DEBT`: they require independent people, systems, infrastructure or authorization.
- 15 are `OPEN_TECH_DEBT`: repository engineering work remains.
- remaining severity: P0 21, P1 48, P2 10.

Machine-readable registers: `docs/audit/closure/KORPUS_v5_REMAINING_DEBT.json` and `.csv`.

## External acceptance debt

- formal production and restricted-data authorization with a named risk owner;
- signed corpus rights, classification, releasability and data-owner manifests;
- independent TEVV, application pentest, AI red-team and parser/container assessment;
- live PostgreSQL/pgvector, Kubernetes, OIDC, S3 Object Lock, KMS/HSM and remote-anchor evidence;
- production load, soak, chaos, rollback, PITR and measured RTO/RPO;
- human gold dataset, blinded holdout and inter-annotator agreement;
- GitLab protected-branch/tag policy and trusted-runner evidence;
- signed build provenance, artifact signing and immutable registry promotion;
- on-call, incident exercises, SLO/error-budget operation and capacity ownership.

## Open engineering debt

- hash-locked Python dependency artifacts and fully immutable container/tool image digests;
- decomposition of the large SQL repository and security configuration validator;
- removal or narrowing of broad exception handlers in critical paths;
- corpus-scale table, number, unit and formula evaluation;
- embedding backfill/model-migration orchestration and drift monitoring;
- production SIEM export, retention and correlation integration;
- executable retention/deletion/legal-hold scheduler and reconciliation;
- reviewer/admin web workflows and accessibility validation;
- live-serving OpenTelemetry health probe and durable telemetry backend;
- environment drift and cost/capacity governance against a real cluster;
- complete dependency/license inventory with legal review.

The machine-readable source of truth is `docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json`.
