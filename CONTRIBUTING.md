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
