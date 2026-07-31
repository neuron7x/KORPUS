# Agent execution contract

This repository may be modified by Codex and Claude Code, but agents are execution workers, not authorities.

## Mandatory topology

- One issue -> one branch -> one isolated Git worktree -> one merge request.
- Never run two agents in the same worktree or Git index.
- No direct pushes to `main`.
- The implementation agent cannot approve its own merge request.
- Every task must state acceptance predicates, forbidden changes, affected trust boundary, and rollback.
- Restricted corpus, production credentials, and real personal data are never mounted into an agent worktree.

## Required agent output

1. changed files;
2. commands executed;
3. tests and exact results;
4. unresolved uncertainty;
5. security/data-classification impact;
6. rollback instructions.

## Fail-closed rules

- No placeholder `pass`, fake benchmark, invented citation, or silent fallback.
- No authorization attribute may come from a query body.
- No retrieved text may alter system or tool policy.
- A failing invariant blocks merge.
