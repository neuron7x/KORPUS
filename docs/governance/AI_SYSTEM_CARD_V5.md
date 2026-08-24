# KORPUS AI System Card — v5

## Decision boundary

KORPUS is an evidence retrieval and controlled publication system. It is not an autonomous command, targeting, medical, legal, disciplinary, personnel, or operational decision-maker. The only automatically emitted substantive claims are exact substrings of approved evidence spans. Any unsupported, contradictory, inaccessible, stale, uncalibrated, or dependency-degraded state must produce abstention or human-review status.

## Intended users

- corpus stewards who ingest and classify sources;
- credentialed metadata and content reviewers;
- credentialed approvers with corpus and authority scope;
- authenticated readers whose clearance, corpus grants, compartments, and entitlements are projected server-side;
- auditors and reliability/security operators.

## Prohibited uses

- treating ranking utility as probability or authority;
- using the system as the sole basis for high-consequence action;
- ingesting material without recorded rights and handling authority;
- transmitting restricted corpus text or sensitive queries to an external model/embedding service unless the corpus policy explicitly permits the operation;
- bypassing review, provenance, temporal validity, access, calibration, or audit gates;
- using local/development credentials in controlled environments.

## Killable safety invariants

1. Unauthorized text is filtered in the database before application candidate materialization.
2. Token privilege claims cannot directly grant application roles, clearance, corpus access, or compartments.
3. A controlled review transition requires an active stage-, corpus-, authority-, and time-scoped reviewer credential.
4. Every answer claim equals a cited source substring and verifies by span ID, offsets, quote hash, and source hash.
5. Conflicting approved evidence stops automated answering.
6. Source content is scanned, type-verified, parsed out of process, quality-gated, and reviewed before approval.
7. Corpus governance must authorize indexing, OCR, citation, export, deletion, and external embedding independently.
8. Calibration is bound to the exact dataset, evaluation protocol, system manifest, and profile digest.
9. Audit event, database head, durable outbox, and external monotonic anchor must reconcile.
10. Missing evidence or missing operational proof is a refusal, not an inferred PASS.

## Harm model

| Harm | Primary prevention | Detection | Recovery |
|---|---|---|---|
| restricted-data disclosure | entitlement projection, ABAC, compartments, PostgreSQL RLS | leakage evals, audit/SIEM events, incident-specific canaries | revoke grants, disable corpus, rotate credentials, reconstruct affected releases |
| false normative answer | approved/current versions, exact extractive claims, contradiction and abstention gates | blind corpus evaluation, citation verification, complaint/incident samples | retract release, supersede source, invalidate cache/index, re-evaluate |
| poisoned corpus | detached source signatures, malware scanning, parser sandbox, near-duplicate and quality review barriers | source/reviewer audit, poisoning red-team, inventory reconciliation | quarantine/reject, revoke key/reviewer credential, rebuild corpus release |
| silent audit rewrite | hash chain, CAS head, HMAC, outbox, remote monotonic anchor | readiness reconciliation and independent anchor comparison | incident freeze, restore verified backup, rotate keys, re-anchor |
| third-party data egress | per-corpus operation policy and fail-closed embedding authorization | egress logs, DLP, provider audit | disable integration, revoke token, rotate secrets, notify owner |

## Human oversight

- metadata review, content review, and approval are separate stages;
- controlled mode requires separate subjects and recorded credentials;
- reviewer grants are revocable, time-bounded, corpus-bounded, and authority-bounded;
- contradictory evidence and high-risk queries require explicit human resolution;
- production authorization and residual-risk acceptance remain external accountable decisions.

## Current evidence boundary

Local tests, adversarial cases, mutation tests, migration checks, static Kubernetes contracts, and clean-room packaging prove only encoded predicates in the supplied environment. They do not prove official corpus authority, legal rights, independent penetration resistance, live service behavior, production SLOs, or government/military authorization.
