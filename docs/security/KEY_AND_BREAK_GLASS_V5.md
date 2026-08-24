# Key Rotation and Break-Glass Protocol — v5

## Key domains

OIDC client credentials; browser session encryption; audit HMAC; remote anchor authentication; source-signing trust roots; reviewer registry signing/approval authority; object-store credentials; database roles; backup encryption; artifact signing; KMS/HSM administration.

## Rotation invariants

- keys are identified by immutable key ID and never overwritten in place;
- verification supports an overlap window while issuance uses only the new key;
- revoked keys fail immediately for new operations and trigger impact analysis;
- historical evidence remains verifiable through retained public metadata;
- rotation, rollback, destruction and recovery are dual-controlled and audited;
- secrets never appear in source, image layers, logs, command history or artifacts.

## Break glass

Break-glass access must be time-limited, purpose-bound, separately authenticated, approved by two accountable people, recorded outside the affected trust domain, and followed by credential rotation and retrospective review. The repository contains no production PAM implementation; live break-glass readiness remains EXTERNAL_DEBT.
