# Security and Policy Model

The gateway is a Policy Enforcement Point. It must use the live canonical KORPUS policy
mechanism unless a separate policy engine is an explicit current architecture decision.

## Trusted policy inputs

Only server/canonical sources:
- authenticated subject;
- trusted roles/clearance/compartments/account attributes;
- server-side entitlement;
- registered capability id/version/effect;
- server-derived logical resource;
- deployment/egress/data policy.

Untrusted:
- request `role`, `admin`, `authorized`, `trusted`;
- model claims/tool arguments;
- MCP annotations/descriptions;
- provider scopes interpreted beyond transport purpose;
- provider output;
- adapter-generated privilege.

## Order

```text
resolve exact capability/resource/effect
 -> canonical authorization
 -> contract validation
 -> effect guard
 -> execute
```

Cheap parsing may precede policy only to derive the policy resource and must not contact the
provider or materialize protected content.

## Confused deputy

Keep separate:
1. KORPUS subject;
2. KORPUS capability;
3. logical resource/effect;
4. provider credential.

A provider credential with broad rights cannot widen the KORPUS subject's rights.

## Egress

Action permission and data-export permission are separate predicates. Provider credentials are
minimum-scope, secret-managed, never LLM-visible, and never stored in capability manifests.
