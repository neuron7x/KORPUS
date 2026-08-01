# ACT-18 — Canonical browser-session encoding

- Issue ID: `KORPUS-ACT-18`.
- Value hypothesis: an authenticated browser envelope should have one accepted textual representation so that mutation, logging and incident correlation cannot disagree about token identity.
- Linked findings: conference browser-security follow-up; no external finding is closed.
- Trust boundary: untrusted cookie string → Base64URL decoder → AES-GCM authenticated session envelope.
- Allowed files: browser OIDC codec/test, relevant mutation target, this contract and verifier index.
- Forbidden files: OIDC authorization semantics, cookie policy weakening, production identity configuration, migrations and frozen audit source.
- Killable invariants: decoder accepts only the codec's unpadded canonical Base64URL representation; byte-equivalent aliases, altered ciphertext, malformed encoding, wrong kind and expired envelopes fail closed.
- Adversarial cases: alternate final character differing only in unused Base64 bits, arbitrary final-character mutation and expired token.
- Acceptance predicates: byte-equivalent alias is constructed and rejected; the randomized test passes 20 consecutive executions; dedicated mutant is killed; full API/browser/live gates remain green.
- Migration/data impact: none.
- Rollback: revert the bounded ACT-18 commit; no state rollback is required.
- Commands executed: 20 repeated focused tests, pinned full-source mypy and changed-source Ruff; full regressions and final live gates recorded after commit.
- Evidence generated: command output and final ignored receipts; session tokens are not retained.
- Unexecuted gates: GitLab pipeline and independent clean-room verification.
- Residual uncertainty: canonical local session envelopes do not constitute production OIDC provider evidence or production authorization.
