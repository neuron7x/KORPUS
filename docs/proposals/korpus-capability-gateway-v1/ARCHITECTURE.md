# Architecture

## Decision

KORPUS Capability Gateway v1 is an application-layer governed invocation boundary inside the
existing modular monolith.

```text
Caller
  |
  v
InvocationContext
  |
  v
Capability Gateway Orchestrator
  |----> Canonical KORPUS Identity
  |----> Canonical KORPUS Policy / Egress
  |----> Capability Registry
  |
  v
Input Contract
  |
  v
Effect Guard
  |
  v
Adapter Port ----> internal / HTTP / MCP / future adapters
  |
  v
Output Contract
  |
  v
Evidence Gate
  |
  v
Canonical Audit
  |
  v
Governed Result
```

## Trust boundaries

- **Authority boundary:** only canonical KORPUS identity/policy may authorize.
- **Capability metadata boundary:** metadata describes an operation; it does not permit it.
- **Adapter boundary:** adapter receives an already-constrained execution context.
- **Provider boundary:** remote responses/auth metadata are untrusted for KORPUS authority.
- **Model boundary:** an LLM may propose an invocation but cannot authorize it.

## Execution law

```text
Execute(i) =
  ResolvedExactCapability(i)
  AND CanonicalPolicyAllow(i)
  AND InputValid(i)
  AND EffectGuardSatisfied(i)
```

No external call occurs if any term is false or unknown.

```text
ReturnCritical(r) =
  OutputValid(r)
  AND RequiredEvidenceValid(r)
  AND RequiredAuditCommitted(r)
```

## No parallel authority stack

Forbidden:
- caller `trusted=true` / `authorized=true`;
- adapter-local RBAC overriding KORPUS;
- MCP token treated as KORPUS permission;
- provider output used as a policy decision;
- second audit/evidence truth store;
- new release identity.

## Version binding

Every execution binds logical capability id/version, adapter id/version, input/output schema
digests, invocation id, policy-decision reference, service/release identity, input digest and,
when present, output/evidence/receipt digests.

## Discovery rule

Discovery is permissive; execution is restrictive. A new external tool begins as
`DISCOVERED_UNTRUSTED` and cannot execute until a local contract, effect class, policy mapping,
evidence rule and negative controls are established.
