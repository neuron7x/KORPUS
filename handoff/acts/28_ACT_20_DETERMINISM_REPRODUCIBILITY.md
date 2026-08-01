# ACT-20 — Determinism and reproducibility gate

- Value hypothesis: exact repeated hashes expose semantic or source-manifest variance that ordinary green tests can hide.
- Linked findings: `SUP-001`, `SUP-002`, `SUP-003`, `OPS-001`, `OPS-004`; none is closed by this local act.
- Trust boundary: committed source and frozen eval inputs → isolated producers → exact artifacts → fail-closed evidence.
- Allowed files: determinism producer/tests, deterministic mutation harness, assurance documentation, CI wiring, this contract and verifier index.
- Forbidden files: frozen audit source, production signing keys, RLS/identity policy and manufactured historical evidence.
- Killable invariants: every expected run exists; full artifact hashes are identical; report contradiction fails; production authorization remains false.
- Adversarial cases: one changed hash, missing repetition, malformed hash, producer failure and false PASS.
- Acceptance: focused/full tests, 20-run stress, mutation/eval/migration and repository validators pass; CI retains evidence.
- Rollback: revert the ACT-20 commit; no data or migration rollback.
- Migration impact: none.
- Unexecuted: independent runner rebuild, registry signing/admission, cross-OS/GPU proof and production load.
- Residual uncertainty: observed equality cannot prove equality for all future executions or all hardware.
