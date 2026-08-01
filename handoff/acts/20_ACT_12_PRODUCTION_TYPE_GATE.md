# ACT-12 — Production type gate

- Issue ID: KORPUS-ACT-12
- Value hypothesis: a hermetic full-source type gate exposes interface drift before runtime and cannot conceal a failed command behind a later success.
- Audit finding IDs: engineering assurance follow-up; no external finding is claimed closed.
- Trust boundary touched: API production typing, configuration validation, external HTTP/S3 client boundaries, repository result materialization.
- Files/modules allowed: `apps/api/src/korpus/`, focused API tests, the deterministic mutation harness, this act contract, verifier evidence index.
- Files/modules forbidden: `docs/audit/source/`, migration history, authorization policies, production configuration or secrets.
- Invariants that may fail: full `apps/api/src` mypy must return zero errors; runtime validation remains fail-closed; no unchecked external value crosses a typed boundary.
- Null/adversarial cases: absent optional configuration, malformed browser envelope, absent embedding client, untyped S3 response, SQLAlchemy sequence result, failed first command in a shell gate.
- Acceptance predicates: pinned dev lock installs with `--no-deps`; `pip check` passes; full-source mypy passes under `set -euo pipefail`; changed-source Ruff and relevant tests pass; no new ignore suppressions; final live gates are regenerated after the repair.
- Migration/data impact: none.
- Rollback: revert the bounded ACT-12 commit; no database rollback is required.
- Commands executed: pinned-environment `pip check`; full-source `mypy`; changed-source `ruff`; focused 33-test shard; full API suite. Every accepted chain used `set -euo pipefail`.
- Evidence artifacts: terminal logs and final machine reports under `var/`; generated evidence and secrets remain uncommitted.
- Gates not executed: independent post-change reproduction and GitLab pipeline remain external until branch publication.
- Remaining uncertainty/debt: static typing cannot prove runtime authorization, PostgreSQL RLS, or production readiness; those require separate live gates and independent verification.

## Baseline

Full-source mypy reported 21 errors across 12 production modules. A prior multi-command shell invocation returned the status of a later successful command, demonstrating a hidden-failure hazard; that invocation is not accepted as a passing gate.

## Local result

- `pip check`: PASS (`No broken requirements found`).
- full-source mypy: PASS (`44 source files`).
- changed-source Ruff: PASS.
- focused tests: PASS (`33 passed`).
- full API tests: PASS (`198 passed, 1 skipped`; the skip is the deliberately environment-gated PostgreSQL test and is not live PostgreSQL evidence).
- Mutation baseline: FAIL (`25/25` applicable mutants killed, but stale indentation made `M21_CSRF_GATE_BYPASS` invalid); the harness must reject this condition and is repaired rather than reported as PASS.
- Mutation repair result: PASS (`26/26` valid mutants killed, zero survived, zero invalid, score `1.0`). The whole legacy mutation script still has pre-existing Ruff findings, so no script-wide Ruff PASS is claimed.
- Live PostgreSQL and browser evidence must be regenerated from the final committed candidate before ACT-12 is verifier-ready.
