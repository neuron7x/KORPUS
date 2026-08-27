# Independent TEVV Plan — v5

## Independence

The evaluator must not be the implementer or the model that generated the implementation. Evaluation data, attack cases, scoring code, and acceptance thresholds are frozen before the candidate release is exposed.

## Required suites

1. blind real-corpus retrieval with stratified slices by document type, age, authority, classification, scan quality and language;
2. human annotation with adjudication and inter-annotator agreement;

Before annotation or ingestion, run `make corpus-admission MANIFEST=<manifest.json>
ROOT=<fetched-directory>`. A passing receipt proves that every ingestible file is listed,
byte-bound by SHA-256 and carries explicit owner, rights, classification, releasability,
retention and access-policy references. It does not establish that those human/legal
decisions are true; the accountable owners must still sign the resulting inventory.
3. exact citation correctness/completeness and temporal-version correctness;
4. abstention precision/recall under missing, ambiguous, contradictory and unauthorized evidence;
5. tables, numbers, units, formulas, footnotes, annexes and OCR corruption;
6. prompt injection, indirect injection, corpus poisoning, metadata poisoning, query evasion and denial-of-service;
7. API/cloud penetration test and identity/RLS noninterference;
8. source/reviewer key revocation and compromised-credential exercises;
9. load, soak, chaos, failover, PITR, backup restore and corpus rollback;
10. supply-chain substitution, unsigned artifact and vulnerable dependency tests.

## Acceptance

Raw cases, annotations, evaluator versions, seeds, environment, candidate commit, corpus release, model IDs and complete results are retained. Aggregate scores cannot hide a failed high-consequence slice. Every failure maps to an owner, reproducer, remediation commit and independent retest.
