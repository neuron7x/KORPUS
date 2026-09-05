# Finite Implementation Work Packages

## WP0 — Live baseline and seam map
Exact HEAD, clean worktree, dependency inventory, canonical identity/policy/evidence/audit/
egress/config/bootstrap/release paths. No repair during discovery.

## WP1 — Freeze v1 contracts
Freeze capability/effect/state/error models and `CGW-R001..CGW-R020`.

## WP2 — Registry and contract validation
Exact id/version registry, lifecycle, strict input/output validation, schema digests.

## WP3 — Canonical policy integration
Trusted policy input builder, pre-execution decision, decision correlation, no caller/provider
authority.

## WP4 — Deterministic internal adapter
No-network read-only adapter proving complete gateway flow.

## WP5 — Governed HTTP adapter
Provider allowlist/config, egress policy, bounds, timeout, redirect policy, normalized errors.

## WP6 — Evidence and audit
Bind output/evidence/audit to invocation, exact capability/adapter/release.

## WP7 — Side-effect engine (optional profile)
Durable idempotency, concurrency, provider receipt, unknown-outcome reconciliation.

## WP8 — MCP adapter (optional profile)
Discovery staging, local mappings, session/auth isolation, schema drift controls.

## WP9 — Observability
Bounded-cardinality OTel/Prometheus, no secret/content labels.

## WP10 — Falsification suite
Unit, property, metamorphic, adversarial, concurrency, integration, critical mutation targets.

## WP11 — Compatibility/migration
Gateway-disabled regression, no authorization widening, DB migration/recovery if effects add
persistence.

## WP12 — Clean-room reproduction
Fresh worktree/clone, exact candidate, no stale local artifacts.

## WP13 — Owner handoff
One finite evidence packet; final state `READY_FOR_OWNER_APPROVAL`.
