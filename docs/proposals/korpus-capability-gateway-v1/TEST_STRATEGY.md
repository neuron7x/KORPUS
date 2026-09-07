# Test Strategy

Tests are organized by invariant, not just layer.

## Unit
Registry resolution, lifecycle, schemas, canonicalization/digests, errors, effect transitions.

## Property / metamorphic
- adding untrusted trust fields never increases permission;
- JSON key reordering preserves canonical digest;
- reducing subject privilege cannot increase visible/executable capabilities;
- changing capability version changes execution binding;
- output/evidence digest mismatch always fails;
- one idempotency key cannot bind two requests.

## Adversarial
Prompt/tool-description injection, SSRF-style URL abuse, header injection, oversized/deep JSON,
credential reflection, capability substitution, provider/schema drift, confused deputy.

## Concurrency
Same-key replay races, same-key different-payload races, pending/unknown/reconcile transitions,
disable/quarantine during inflight work.

## Integration
Canonical identity/policy/audit/evidence/egress seams, HTTP provider, real PostgreSQL if durable
idempotency is added, MCP session only when MCP profile is enabled.

## Mutation priorities
Policy-deny branch, unknown capability, input/output validation, evidence freshness/binding,
idempotency conflict, required audit, drift quarantine.

Coverage percentage alone is not release authority.
