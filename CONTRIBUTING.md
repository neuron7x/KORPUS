# Contributing

All changes begin with a GitHub issue and an isolated worktree created by `scripts/create_agent_worktree.sh`.

A pull request must include the value hypothesis, affected trust boundary, killable invariants, negative tests, exact commands/results, migration and rollback, and an independent verifier. Direct pushes, production data in fixtures, client-derived authorization, silent fallbacks, fake benchmarks and unresolved implementation placeholders are prohibited.

Run before review:

```bash
make validate
make assurance
make api-lint
make package
```

GitHub is the primary CI transport for the `v0.1.x` line. The protected merge path is defined by `.github/workflows/` plus `docs/operations/GITHUB_REPOSITORY_POLICY.md`. The retained GitLab pipeline is a legacy parity/evidence surface during migration and does not define a second semantic policy.

Internal script helpers `scripts/manifest_paths.py` and `scripts/openapi_normalization.py` are imported by the manifest and OpenAPI runners respectively; they are library modules, not standalone CLI entry points.

## Committing

Use `scripts/guarded_commit.sh -m "message" -- path [path...]`.

It runs `make validate` first and refuses on failure, and it refuses to stage anything you
did not name. Three commits on 2026-08-29 were pushed with the tree red: twice the check ran
in a compound command whose `&&` was consumed by an `echo` before `git commit`, and once
`git add -A ':!path'` staged a parallel session's edits — exclusions apply to untracked
paths only, never to files git already tracks.

`GATES="validate api-test" scripts/guarded_commit.sh ...` widens the check. Before pushing,
`make verify-clean-clone` answers the question the working tree cannot: does the commit
stand on its own. Five defects that session passed here and failed there.
