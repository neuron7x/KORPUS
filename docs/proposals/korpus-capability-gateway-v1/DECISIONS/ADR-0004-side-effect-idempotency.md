# ADR-0004 — Durable Idempotency for Side Effects
**Status:** PROPOSED

Every effectful capability requires durable idempotency binding and explicit unknown-outcome
semantics. Retrying an ambiguous effect is allowed only when duplication is prevented under
the same provider/KORPUS effect identity.
