# Function Catalog

The names below are normative concepts, not mandatory Python symbols.

## `invoke_capability(request, runtime_context)`

Sequence:
1. allocate invocation id;
2. resolve exact capability id/version;
3. derive trusted policy input;
4. call canonical KORPUS authorization;
5. validate normalized input;
6. apply effect/idempotency guard;
7. execute adapter within bounded timeout/cancellation;
8. validate normalized output;
9. derive and validate required evidence;
10. append canonical audit;
11. return governed result.

Postcondition: no success without all mandatory post-execution gates.

## Registry functions

- `register_capability(spec)` — validate immutable identity, contracts, effect, policy map,
  evidence profile and lifecycle; registration grants no subject permission.
- `resolve_capability_exact(id, version)` — no fuzzy fallback or silent latest-version swap.
- `list_capabilities_for_subject(subject, context)` — policy-filtered visibility only.
- `describe_capability_for_subject(subject, id)` — sanitized local description; remote text
  remains untrusted.

## Contract functions

- `validate_input(spec, raw)` — strict schema, bounds, normalization, no authority fields.
- `validate_output(spec, raw)` — schema, size/data policy, no provider authority escalation.
- `schema_digest(schema)` — canonical serialization + SHA-256.

## Policy functions

- `build_capability_policy_input(...)` — trusted subject, registered capability/effect,
  server-derived resource, data/egress class.
- `authorize_capability(...)` — call canonical KORPUS policy; result is correlation evidence,
  not a reusable capability token.

## Side-effect functions

- `prepare_effect_guard(...)` — explicit effect auth + idempotency binding.
- `finalize_effect_receipt(...)` — bind provider receipt/outcome.
- `reconcile_unknown_effect(...)` — resolve ambiguous timeout without duplicate execution.

## Adapter functions

- `execute_adapter(...)` — receives constrained context only.
- `map_provider_error(...)` — stable bounded domain error; no secret/raw sensitive leakage.

## Evidence/audit/operations

- `derive_evidence(...)`
- `validate_evidence(...)`
- `append_integration_audit(...)`
- `emit_integration_telemetry(...)`
- `health_check(adapter_id)` — reachability, never authority.
- `acceptance_check(capability_id, fixture_set)` — exact-state conformance evidence.
