# Production runbook v6 — release-candidate operations

## Scope

This runbook defines operational decisions for a KORPUS production candidate. It intentionally does **not** invent production latency or availability targets. `SLO_AND_RELEASE_POLICY_V5.md` remains authoritative: numeric production SLOs are unknown until representative pilot traffic, corpus scale, dependency topology and consequence are measured.

## 1. Pre-deployment identity

Record and compare, before any deployment action:

1. release tag;
2. source-tree SHA-256;
3. package SHA-256;
4. SOURCE_MANIFEST root;
5. DISTRIBUTION_MANIFEST root;
6. migration head;
7. configuration/profile digests;
8. SBOM digest;
9. assurance evidence digest.

If any identity differs between approval and deployment, the candidate is stale. Do not “update the hash in place”; create/re-evaluate a new release identity.

## 2. Database migration transaction

- Confirm backup freshness and successful restore drill evidence for the same release window.
- Apply migrations using the deployment identity, not an application superuser.
- Verify expected schema revision and required indexes/constraints.
- Run application-role access probes after migration.
- Run read/write smoke tests through the application boundary.
- If the migration is not reversibly safe, rollback is application-forward plus database recovery, never an unreviewed downgrade.

## 3. Canary deployment

The canary phase measures; it does not inherit an arbitrary “99.9%” target. Collect at minimum:

- authenticated success/error counts by endpoint class;
- p50/p95/p99 request and retrieval latency;
- denial/abstention/unsupported-claim/citation-verification rates;
- DB pool occupancy, lock waits and transaction timeout counts;
- ingestion queue age/retries/dead letters;
- audit-anchor backlog count and age;
- object reconciliation drift;
- provider failures/egress denials;
- cost per accepted answer and per ingested/reviewed document.

The pilot establishes an empirical baseline. A production SLO is approved only after the baseline is representative and consequences of failure are classified.

## 4. Fail-closed triggers

Immediately deny the affected operation when any of these are uncertain or invalid:

- authentication identity;
- authorization scope;
- corpus/version identity;
- evidence integrity;
- reviewer separation;
- malware/parser safety policy when required;
- audit durability for controlled state transitions;
- database isolation / policy enforcement;
- release/source identity.

Telemetry display failure may degrade only when the underlying event remains durable.

## 5. Incident classes

### P0 — confidentiality / authority / integrity breach

Examples: cross-tenant disclosure, authorization bypass, forged approval, stale authority answered as current, package identity mismatch. Action: withdraw candidate/release, preserve evidence, rotate compromised material if applicable, block promotion, start independent review.

### P1 — material availability/reliability failure

Examples: persistent database saturation, audit-anchor backlog beyond approved pilot envelope, ingestion dead-letter surge, restore failure. Action: stop scale-out/promotion and invoke recovery plan.

### P2 — degradable subsystem

Examples: optional display telemetry, non-required semantic enhancement under a profile that explicitly validates lexical operation. Action: degrade only within declared policy.

## 6. Rollback decision tree

1. Is source/package identity intact? If no → withdraw release.
2. Is data integrity intact? If no/unknown → stop writes and recover from verified state.
3. Is schema backward compatible with previous application? If yes → application rollback may be permitted.
4. If not → forward fix or rehearsed database recovery only.
5. Re-run smoke, authorization, audit and evidence-integrity probes after recovery.

## 7. Post-deployment evidence

Persist deployment identity, environment identity, canary measurement window, operator/verifier identities, migration output, rollback capability, and signed production gate artifacts. “Deployment succeeded” is not evidence of safe operation; observed SLIs and negative controls are required.
