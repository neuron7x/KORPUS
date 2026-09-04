# Migration and Compatibility

The gateway is additive and disabled by default until capability configuration explicitly
enables it. Existing answer/retrieval behavior must remain unchanged when disabled.

A read-only core should avoid DB migration if canonical audit mechanisms already support the
needed record. Durable side-effect idempotency may require a migration; if so, enforce
uniqueness/concurrency in PostgreSQL, test forward/recovery behavior, and preserve effect
receipts across rollback.

Do not expose a generic public `/invoke-anything` endpoint by default. Any public API must
prevent caller-supplied identity/role/clearance and make effectful consent/authorization
explicit.

Rollback should disable capabilities first where practical, revert code second, and preserve
audit/idempotency records needed to reconcile already-attempted effects.
