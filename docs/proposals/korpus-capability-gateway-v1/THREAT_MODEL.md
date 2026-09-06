# Threat Model

| Threat | Example | Control |
|---|---|---|
| confused deputy | low-privilege user drives privileged provider token | canonical policy on logical action/resource |
| capability substitution | read resolves to write | exact id/version |
| request authority spoof | body says admin/trusted | strict schema + canonical identity |
| output authority spoof | provider returns `trusted=true` | output never becomes policy |
| MCP prompt injection | tool description says ignore policy | remote metadata stays data |
| evidence fabrication | receipt/source claims wrong output | binding + provenance + freshness |
| SSRF | arbitrary provider URL | server-side provider allowlist/config |
| secret exfiltration | tool requests token/env | minimal execution context + egress policy |
| duplicate side effect | retry duplicates action | durable idempotency + reconciliation |
| ambiguous timeout | effect committed but response lost | `OUTCOME_UNKNOWN` |
| schema/effect drift | provider broadens tool | digest drift -> disable/quarantine |
| audit bypass | adapter returns directly | orchestrator owns finalization |
| telemetry leakage | body in span labels | bounded semantic attributes |
| supply-chain substitution | wrong adapter/build executes | exact release/adapter provenance |

The critical design error to prevent is an actor that both proposes an action and supplies the
authority that permits that action.
