# ACT-23 — Browser OIDC protocol-boundary assurance

- Value hypothesis: browser authentication must collapse transport, parser and protocol variance into deterministic fail-closed outcomes while accepting only a narrow OAuth/OIDC token envelope.
- Linked findings: `IAM-002`; no external finding is closed.
- Trust boundary: browser flow state and remote token endpoint bytes → authenticated session envelope → server-verified identity.
- Allowed files: browser OIDC module/tests, focused mutation/CI evidence, this act and verifier index.
- Forbidden files: production IdP configuration, real tokens/secrets, entitlement semantics, RLS and frozen audit source.
- Killable invariants: canonical Base64URL; authenticated version/kind/timestamps/payload; `exp > iat`; nonempty tokens; Bearer token type; bounded integer lifetime; normalized transport/parser failures.
- Adversarial cases: authenticated malformed envelope, bool timestamps, reversed lifetime, JSON array, invalid JSON, 503, ConnectError, empty tokens, wrong token type and out-of-range TTL.
- Acceptance: meaningful 100% branch coverage for browser OIDC, critical mutants killed, full tests/eval/determinism green.
- Rollback: revert ACT-23 commit; no data migration.
- Residual uncertainty: mock transport is not production IdP interoperability, authorization-code replay testing or external red-team evidence.

## Demonstrated result

- Pre-fix transport errors escaped the stable browser-session error boundary; non-object JSON raised an uncontrolled attribute error.
- Pre-fix responses accepted empty token strings, omitted/wrong OAuth token type, and envelopes did not require `exp > iat` or reject boolean timestamps explicitly.
- Focused proof: 27 tests pass; `118/118` statements and `34/34` branches covered (`100%`, zero exclusions).
- CI consequence: `api:browser-oidc` enforces branch coverage 100% and retains JSON/JUnit.
- Mutation consequence: M30 canonical encoding, M32 token type and M33 reversed lifetime must all be killed.
