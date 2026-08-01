# KORPUS v5 — system architecture

## System boundary

KORPUS is an evidence-bound document control, retrieval and review system. It is not an autonomous authority. Its admissible output is either an extractive claim bound to an approved immutable source span or an explicit abstention.

## Trust path

```text
OIDC authentication
  -> server-side entitlement projection
  -> corpus governance and need-to-know compartments
  -> PostgreSQL FORCE RLS before text materialization
  -> temporally valid approved document versions
  -> bounded lexical candidate retrieval
  -> optional policy-authorized calibrated semantic fusion
  -> deterministic reranking, contradiction and support gates
  -> exact claim/span offsets and hashes
  -> business transaction plus audit outbox
  -> authenticated monotonic remote anchor
```

## Ingestion path

```text
streamed bounded upload
  -> quarantine object store
  -> MIME/signature validation
  -> malware scan
  -> isolated parser subprocess
  -> bounded OCR and extraction-quality assessment
  -> source-signature validation
  -> exact/near-duplicate detection
  -> durable leased job with retry/dead-letter state
  -> metadata review
  -> content review
  -> approval by separately authorized credentials
  -> immutable current version and evidence spans
```

## Authorization planes

1. OIDC establishes subject identity and authentication assurance.
2. A content-addressed entitlement profile maps the subject to roles, clearance, corpora and compartments. Token-supplied privilege claims are not authoritative.
3. A content-addressed corpus-governance profile constrains classification, authority class, OCR, indexing, citation, export, deletion and external embedding.
4. A content-addressed reviewer registry constrains review stage, corpus, authority, validity interval and revocation.
5. Application ABAC and PostgreSQL RLS are independent barriers.

## Runtime topology

- Local integration: Docker Compose, loopback-only web ingress, internal edge/backend networks, API-only egress.
- Production reference: Kubernetes/Kustomize with restricted Pod Security, non-root containers, default-deny NetworkPolicies, separate API/worker service accounts, migration Job, HPA and PDB.
- PostgreSQL/pgvector is the authoritative metadata, state and retrieval store.
- S3-compatible object storage keeps quarantine and immutable content under separate prefixes and policies.
- ClamAV and parser subprocesses are non-authoritative isolation controls.
- OpenTelemetry/Prometheus provide bounded-cardinality telemetry; they do not replace audit evidence.

## State invariants

1. Unauthorized source text is filtered before ranking or model egress.
2. Only approved versions valid at the requested date are retrievable.
3. Exactly one current version exists per document.
4. Every accepted claim equals a cited substring and validates by offsets, quote hash and source hash.
5. Unsupported, contradictory, uncalibrated or unavailable semantic evidence causes abstention or lexical fallback according to the signed profile.
6. Review stages require distinct, scoped, unexpired, non-revoked credentials in controlled environments.
7. Business state and local audit event commit atomically; remote anchoring is delivered by durable outbox.
8. Calibration binds thresholds to dataset, evaluation protocol, system manifest and model configuration.
9. External embeddings are denied before egress unless the corpus policy explicitly permits them.
10. Release evidence must match committed source and classify all frozen audit findings.

## Explicit non-claims

The repository does not prove rights to a real corpus, military authorization, external service availability, production SLOs, independent penetration resistance, human-label validity, live disaster recovery or absence of unknown vulnerabilities. Those are external acceptance gates recorded in the v5 debt and findings registers.
