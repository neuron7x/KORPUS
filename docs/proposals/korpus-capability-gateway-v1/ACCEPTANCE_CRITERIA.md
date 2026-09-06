# Acceptance Criteria

```text
IntegrationReady =
  ContractValid
  AND PolicyPrecedesExecution
  AND InputValidated
  AND OutputValidated
  AND RequiredEvidenceValid
  AND RequiredAuditSatisfied
  AND NegativeControlsPass
  AND BlockingUnknown = 0
```

For effectful operations:

```text
SideEffectAllowed =
  PreExecutionIntegrationReady
  AND ExplicitEffectAuthorization
  AND IdempotencyBound
  AND EffectClassKnown
```

## Frozen v1 requirements

| ID | Requirement |
|---|---|
| CGW-R001 | unknown capability never executes |
| CGW-R002 | policy deny/unknown never executes |
| CGW-R003 | invalid input never executes |
| CGW-R004 | exact capability version bound before execution |
| CGW-R005 | invalid output cannot return success |
| CGW-R006 | missing/stale/wrong-bound required evidence cannot support success |
| CGW-R007 | request/adapter/provider metadata cannot supply KORPUS authorization |
| CGW-R008 | effectful operation requires explicit effect authorization |
| CGW-R009 | effectful operation requires idempotency |
| CGW-R010 | idempotency conflict never executes |
| CGW-R011 | ambiguous effect timeout becomes `OUTCOME_UNKNOWN` |
| CGW-R012 | required audit persistence is a success precondition |
| CGW-R013 | secrets do not enter user output or telemetry labels |
| CGW-R014 | MCP/remote metadata is untrusted discovery data |
| CGW-R015 | schema/effect drift cannot silently widen capability |
| CGW-R016 | disabled gateway preserves existing product path |
| CGW-R017 | canonical KORPUS policy/evidence/audit remain authoritative |
| CGW-R018 | exact-state clean-room reproduction passes |
| CGW-R019 | fresh-context verifier reproduces blocking controls |
| CGW-R020 | final production authority remains with Owner |

P0 means an actual violation of a frozen critical invariant or a mandatory verifier that can
false-PASS one. Non-P0 discoveries after candidate freeze go to N+1.
