# Evidence and Audit Model

## Evidence classes

1. policy-decision correlation evidence;
2. execution identity evidence;
3. provider receipt/provenance;
4. factual/source evidence;
5. audit-chain evidence;
6. release/build evidence.

One class cannot substitute for another.

## Evidence binding

Required evidence is valid only when its applicable bindings agree:
- invocation id;
- capability id/version;
- adapter id/version;
- output digest;
- source/provider identity;
- subject/resource where required;
- freshness interval;
- signature/provenance class where required.

A signed but wrong-subject receipt is invalid for the current result.

## Factual material

Remote JSON or MCP output is not automatically admissible KORPUS factual evidence. If it will
support a factual claim, it enters the normal KORPUS evidence-admission/binding path.

## Audit minimum

Record:
event/invocation/correlation ids; canonical subject reference; capability/adapter versions;
policy-decision reference; input digest; effect/idempotency binding; outcome; output/evidence/
receipt digests; start/end time; stable error code; exact service/release identity.

Do not duplicate raw sensitive payloads into audit.

## Audit failure

Where audit commit is a product/security invariant, no successful final result is emitted if
the canonical audit append fails. For non-atomic remote side effects, record pending/unknown
state and reconcile rather than lying about success.
