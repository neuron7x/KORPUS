# KORPUS current system architecture

Current release identity is machine-owned by `apps/api/src/korpus/release.json`.
Historical architecture snapshots (`SYSTEM_V2.md` … `SYSTEM_V5.md`) are retained only as
release history; this file is the current architecture SSOT.

## Product boundary

KORPUS is a subscription-capable evidence-bound web application for controlled curated
knowledge. It is not an autonomous authority. A factual answer is admissible only when
its claims are bound to authorized, approved source spans; otherwise the system abstains.

Current product path:

```text
authenticated user
  -> application account
  -> active commercial entitlement
  -> corpus/security authorization intersection
  -> conversation/query context
  -> authorized retrieval before materialization
  -> temporally valid approved evidence
  -> deterministic evidence/support/contradiction gates
  -> exact extractive claims and citations OR abstention
  -> persistent conversation linkage + tamper-evident audit
```

Commercial access never widens security access. Conversation history may resolve language
context but is never promoted into factual evidence.

## Ingestion and corpus path

```text
bounded upload / approved acquisition source
  -> quarantine
  -> malware/type/parser isolation
  -> OCR/extraction-quality assessment
  -> provenance/signature/rights metadata
  -> exact + near-duplicate checks
  -> durable ingestion job
  -> separated metadata/content/approval review
  -> immutable approved version
  -> evidence spans + derived retrieval structures
```

The doctrine source catalog classifies authority, provenance, rights and verification.
A catalog entry is not corpus authority by itself; ingestion and review remain explicit.

## Identity, account and subscription planes

1. OIDC/BFF establishes authenticated subject identity.
2. Application account persistence establishes the product principal.
3. Billing events drive server-side subscription state through idempotent transitions.
4. Subscription entitlement intersects with, and never overrides, security/corpus policy.
5. Application ABAC and PostgreSQL FORCE RLS remain independent authorization barriers.

## Model-egress plane

External model calls are policy-gated. The GOV-006 material ceiling applies to corpus
material admitted for composition; material above the configured external tier is refused
before transport. A free-text user question has no trustworthy automatic classification in
KORPUS, so enabling an external query planner is an explicit deployment decision that sends
that question to the configured provider. Model output is never a factual source and cannot
bypass evidence admission.

## Runtime topology

- Modular monolith is intentional while answer, authorization, billing, conversation and
  audit invariants share transactional boundaries.
- PostgreSQL/pgvector: authoritative metadata/state and production retrieval store.
- S3-compatible storage: quarantine and immutable content objects.
- API + worker: protected backend plane.
- Responsive PWA/web: consumer and operator surfaces.
- OpenTelemetry/Prometheus: operational telemetry, not audit authority.
- Kubernetes/Kustomize: production reference topology with non-root execution,
  restricted Pod Security and default-deny network policy.

## Source-of-truth boundaries

- protected Git `main`: source code, contracts, migrations and release identity;
- `SOURCE_MANIFEST.json`: exact committed source inventory, excluding itself;
- `DISTRIBUTION_MANIFEST.json`: exact packaged-delivery inventory, excluding itself;
- SQL database: product/corpus state and audit chain;
- content-addressed object store: immutable source bytes;
- search/index artifacts: derived and rebuildable;
- release reports: evidence only for the source digest they name;
- external audit anchor: independently stored checkpoint.

## Killable invariants

1. Unauthorized source text is excluded before ranking, answer construction and model egress.
2. Commercial subscription status cannot widen corpus/security authorization.
3. Conversation history is context, never evidence.
4. Only approved versions valid at the requested date are retrievable.
5. Every admitted factual claim equals a cited source substring and verifies by binding data.
6. Unsupported, contradictory or policy-blocked output abstains/fails closed.
7. Business state and local audit event commit atomically where the operation requires it.
8. External model egress requires an explicit permitted policy state.
9. Billing event identities are idempotent; replay cannot duplicate state transitions.
10. Cross-account conversation access is denied without information disclosure.
11. Current release metadata must agree with the machine release identity.
12. Release evidence must bind the exact committed source tree.
13. Final distribution contents must match the distribution manifest exactly.

## Extraction threshold

A service may be extracted from the modular monolith only after:

1. a versioned contract exists;
2. deterministic replay exists;
3. failure and rollback semantics are tested;
4. cross-service authorization cannot widen access;
5. measured scale pressure justifies the additional failure surface.

## Current non-claims

The repository does not by itself prove corpus rights, external service availability,
production SLO attainment, independent penetration resistance, legal authorization,
human-label validity, live HA/DR effectiveness or production risk-owner approval. Those
remain explicit external gates and must never be inferred from code coverage or test count.
