# Contributing

All changes begin with a GitLab issue and an isolated worktree created by `scripts/create_agent_worktree.sh`.

A merge request must include the value hypothesis, affected trust boundary, killable invariants, negative tests, exact commands/results, migration and rollback, and an independent verifier. Direct pushes, production data in fixtures, client-derived authorization, silent fallbacks, fake benchmarks and unresolved implementation placeholders are prohibited.

Run before review:

```bash
make assurance
make api-lint
make package
```

`make assurance` is the executable local baseline. GitLab additionally runs PostgreSQL integration, secret scanning, dependency audit, SBOM and container builds.

Internal script helpers `scripts/manifest_paths.py` and `scripts/openapi_normalization.py` are imported by the manifest and OpenAPI runners respectively; they are library modules, not standalone CLI entry points.
