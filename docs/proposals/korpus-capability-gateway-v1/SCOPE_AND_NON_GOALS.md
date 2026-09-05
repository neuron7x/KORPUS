# Scope and Non-Goals

## In scope

- internal deterministic functions;
- remote HTTP APIs;
- MCP tools/resources through adapters;
- policy-filtered discovery;
- input/output contracts;
- side-effect classification and idempotency;
- evidence and audit binding;
- telemetry;
- adversarial, property, concurrency, and clean-room verification;
- multi-agent implementation/verification roles;
- finite work acts and release handoff.

## Non-goals

The proposal does not replace KORPUS identity, authorization, evidence admission, audit,
release identity, or corpus policy. It does not create an autonomous tool bus, generic
superuser endpoint, new microservice, mandatory OPA dependency, mandatory MCP SDK, or a new
meta-assurance framework. It does not grant production authority.

## Initial implementation profile

1. Keep v1 in the existing modular monolith.
2. Implement one deterministic read-only internal adapter.
3. Implement one governed read-only HTTP adapter.
4. Add MCP only after the gateway core is stable.
5. Add side effects only after durable idempotency and reconciliation exist.
6. Reuse canonical KORPUS policy/evidence/audit primitives.
