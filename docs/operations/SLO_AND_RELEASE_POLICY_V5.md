# SLO and Release Policy — v5

## Current status

Production SLO numeric targets are UNKNOWN until representative pilot traffic, corpus scale, dependency topology, and mission consequence are measured. Invented availability or latency percentages are prohibited.

## Mandatory SLIs

- successful authenticated request rate by endpoint class;
- p50/p95/p99 end-to-end and retrieval latency;
- abstention, contradiction, unsupported-claim, and access-denial rates;
- citation verification and corpus-version resolution failures;
- ingestion queue age, retries, dead letters, parser/scanner failures;
- audit-anchor backlog count/age and reconciliation failures;
- database pool saturation, lock waits, storage growth, object reconciliation drift;
- backup freshness, restore success, measured RTO/RPO;
- embedding drift, stale/missing index entries, provider failures and egress denials;
- cost per accepted answer and per ingested/reviewed document.

## Release gate

A production release is denied unless:

1. source, tests, assurance and packaged artifact resolve to one immutable commit;
2. all required CI jobs pass without retry masking;
3. migrations pass clean upgrade, compatibility, rollback policy and non-superuser RLS tests;
4. corpus/calibration/governance/reviewer artifacts match configured digests;
5. signed image provenance, SBOM and vulnerability policy pass;
6. canary metrics remain within the approved error budget;
7. rollback of application and corpus release is rehearsed;
8. no unresolved P0/P1 exists without signed, expiring risk acceptance.

## Degraded mode

Authentication, authorization, database isolation, evidence integrity, calibration, malware scanning, parser isolation, corpus policy, or audit anchoring failures are fail-closed. Optional telemetry display may degrade, but the underlying event must remain durably available. Semantic retrieval may be disabled only if the active calibrated profile explicitly validates lexical-only behavior; required semantic mode never silently falls back.
