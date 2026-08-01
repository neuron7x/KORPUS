# ACT-17 — Type-gate package discovery

- Issue ID: `KORPUS-ACT-17`.
- Value hypothesis: full-source static typing is evidence only when mypy deterministically discovers the local source package and analyzes every module under the committed configuration.
- Linked findings: engineering assurance follow-up; no external finding is closed.
- Trust boundary: repository source layout ↔ pinned mypy interpreter ↔ Make/GitLab gate result.
- Allowed files: typed API boundary repairs, Make/GitLab type invocations, this contract and verifier index.
- Forbidden files: type-check suppressions, weaker mypy configuration, runtime authorization policy, migrations, production authorization and frozen audit source.
- Killable invariants: the pinned checker analyzes exactly 44 source files with explicit local package discovery; zero errors; no `ignore` additions; runtime and live boundary tests remain green.
- Adversarial cases: source treated as an untyped installed dependency, package not found, optional calibration paths crossing a required boundary, untyped Starlette state, heterogeneous keyword dictionaries and unchecked readiness metric values.
- Acceptance predicates: the previously weak invocation is reproduced; canonical explicit-package invocation reports 25 errors before repair and zero afterward across 44 files; focused/full tests and final live receipts pass.
- Migration/data impact: none.
- Rollback: revert the bounded ACT-17 commit; no state rollback is required.
- Commands executed: pinned mypy baseline and post-repair command, changed-source Ruff; focused/full regressions and live gates recorded after commit.
- Evidence generated: terminal output and final ignored machine receipts; no secrets.
- Unexecuted gates: GitLab pipeline and independent clean-room verification.
- Residual uncertainty: mypy proves static consistency, not runtime authorization, RLS, production identity or production readiness.
