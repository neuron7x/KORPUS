# Proposed Implementation Commit Sequence

1. `docs: specify KORPUS capability gateway v1`
2. `feat(capabilities): add core contracts and exact registry`
3. `feat(capabilities): bind gateway to canonical authorization`
4. `feat(capabilities): add deterministic internal adapter`
5. `feat(capabilities): add governed HTTP adapter`
6. `feat(capabilities): bind evidence and audit`
7. `test(capabilities): add adversarial and metamorphic controls`
8. `feat(capabilities): add durable side-effect idempotency` — only if enabled
9. `feat(capabilities): add MCP adapter` — only after base closure
10. `test(capabilities): close clean-room conformance`
11. `docs(release): record gateway owner handoff`

Avoid unrelated refactors in these commits.
