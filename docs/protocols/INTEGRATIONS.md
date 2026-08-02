# Integration protocol

## General contract

Every integration has an owner, data-flow diagram, purpose, data classes, credentials,
timeouts, retry/idempotency policy, observability, failure mode, disable switch,
retention, deletion path, test environment and exit plan.

## LLM provider

- Provider adapter receives minimized evidence, pseudonymous safety identifier and a
  versioned prompt contract.
- `store` and region are explicit deployment decisions, not SDK defaults.
- Request/response schemas are validated at the boundary.
- No provider tool can retrieve outside the server-authorized evidence set.
- Model upgrade is a C2 change with eval comparison and rollback.

## Identity provider

OIDC Authorization Code + PKCE; short-lived access tokens; refresh-token rotation;
server-side role/attribute mapping; phishing-resistant MFA for privileged roles.

## Object storage

Private buckets, workload identities, encryption, object versioning, malware quarantine,
short-lived signed URLs, and separate tier policies. Public ACLs are forbidden.

## Messaging/notifications

Use an outbox event; do not call external messengers inside the source transaction.
Messages contain no source text or sensitive query by default.

