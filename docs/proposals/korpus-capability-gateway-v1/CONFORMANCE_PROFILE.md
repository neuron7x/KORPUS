# Conformance Profile — `korpus.capability-gateway.v1`

Base conformance requires all `CGW-R001..CGW-R020` blocking requirements to pass, including
exact capability resolution, canonical pre-execution policy, strict input/output contracts,
required evidence/audit binding, poisoned negative controls, exact-state reproduction and
Owner-only final production authority.

Optional profiles:
- `http-read`
- `mcp`
- `side-effects`

An optional profile is non-blocking when disabled. Once enabled in a candidate, its applicable
requirements become part of that candidate's frozen denominator.
