# ADR-0006: Transactional outbox for external audit anchoring

Status: accepted.

## Decision

Commit each audit event, CAS head update and anchor-outbox record in one database transaction. Deliver the external HMAC anchor after commit and replay undelivered records on startup or explicit reconciliation.

## Rationale

A direct database-then-file write has an unavoidable crash window. Retrying the entire business operation can duplicate effects. The outbox makes anchor delivery recoverable without replaying the source operation.

## Remaining boundary

A local HMAC file detects modification/truncation under separated storage and key assumptions. It is not WORM storage, trusted timestamping, HSM custody or formal nonrepudiation.
