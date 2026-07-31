# Contributing

All changes begin with a GitLab issue and use an isolated worktree created by `scripts/create_agent_worktree.sh`.

A merge request must include acceptance predicates, trust-boundary impact, negative tests, exact commands/results, rollback, and an independent verifier. Direct pushes to `main`, production data in fixtures, client-derived authorization, silent fallbacks, fake benchmarks, and unresolved implementation placeholders are prohibited.

Run before review:

```bash
make check
make web-build
make package
```
