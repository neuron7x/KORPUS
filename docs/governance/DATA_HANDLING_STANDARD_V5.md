# Data Handling Standard — v5

## Executable source of truth

Controlled environments load a SHA-256-bound `CorpusGovernanceProfile`. A corpus without a policy is denied. The policy records:

- data owner and security owner;
- rights reference and releasability statement;
- permitted classification and authority classes;
- independent operation grants for indexing, OCR, citation, external embedding, export, and deletion;
- retention period, legal hold, and declassification rule.

## Required object inventory

Every production corpus object must be associated with all fields below before approval:

| Field | Failure behavior |
|---|---|
| owner | quarantine |
| classification | quarantine |
| rights/reuse authority | quarantine |
| releasability | quarantine |
| retention rule | quarantine |
| legal hold state | deletion denied |
| source hash and object key | ingestion rollback/reconciliation event |
| source signing key | rejection when signatures are required |
| reviewer and approver credential IDs | transition denied |
| version validity/supersession | retrieval denied outside valid interval |

## Data minimization

- browser tokens remain HttpOnly and are not persisted by JavaScript;
- query and evidence content must not become metric labels;
- audit payloads record bounded identifiers and decisions, not arbitrary document bodies;
- external embedding is denied unless all requested corpora explicitly permit it;
- raw uploads remain in quarantine until durable ingestion succeeds;
- rejected and dead-letter objects follow corpus retention and legal-hold policy.

## Deletion and legal hold

The profile rejects simultaneous `legal_hold=true` and permission to delete. Physical deletion requires a separate future deletion executor, authenticated approval, audit event, object-store/version cleanup, index cleanup, and post-action reconciliation. Until that executor and external owner approval exist, deletion readiness is OPEN.
