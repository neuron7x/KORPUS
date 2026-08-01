# ACT-11 — Hermetic Python type gate

- Issue ID: `KORPUS-ACT-11`.
- Value hypothesis: a mandatory CI type gate has no evidentiary value when its pinned
  no-dependency environment cannot import the checker.
- Linked findings: no external finding is closed by this infrastructure repair.
- Trust boundary: committed dependency lock versus clean CI interpreter and mypy execution.
- Allowed files: development lock, type defects exposed in changed assurance modules,
  Alembic fail-closed configuration and separator checks, focused tests, this act.
- Forbidden files: runtime dependency changes, type-check weakening, ignored errors,
  production authorization, frozen audit source.
- Killable invariants: installing the dev lock with `--no-deps` passes `pip check`; mypy imports;
  pinned dependencies satisfy mypy metadata; missing Alembic script location fails explicitly;
  changed assurance modules type-check.
- Pre-fix reproduction: `mypy==2.3.0` requires `pathspec>=1.0.0`, `ast-serialize>=0.6,<1`
  and `librt>=0.13`; the lock pinned pathspec 0.12.1 and omitted the latter packages. Mypy
  failed at import, while pip check reported missing `ast-serialize` after pathspec repair.
- Acceptance predicates: fresh venv no-deps installation and pip check pass; mypy version and
  scoped analysis pass; unit/live regressions remain green; independent verification remains.
- Rollback: revert the bounded ACT-11 commit and restore the prior dev lock.
- Migration impact: none.
- Evidence generated: command output only; no secrets or databases.
- Executed gates: a fresh Python 3.12 venv installed the complete dev lock with `--no-deps`;
  `pip check`, mypy import, scoped mypy, scoped Ruff, 22 focused tests and Alembic graph
  inspection passed. The prior Alembic path-separator warning was removed.
- Unexecuted gates: full GitLab pipeline and independent verifier.
- Residual uncertainty: repository-wide Ruff debt and unrelated historical script type errors
  are not converted into closure by this act.
- Verdict: `PASS_WITH_CAVEATS`; independent post-change verification is required and
  `production_authorized=false`.
