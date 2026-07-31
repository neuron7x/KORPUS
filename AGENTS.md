# Agent execution contract

Codex and Claude Code are execution workers. They do not define truth, approve their own output or receive production authority.

## Mandatory topology

- One issue -> one branch -> one isolated Git worktree -> one merge request.
- Never run two agents in the same worktree, Git index, database or object-store fixture.
- No direct pushes to protected `main`.
- The implementation agent cannot be the independent verifier.
- Restricted corpus, production credentials, personal data and real security material are never mounted into agent worktrees.
- Search indexes and generated artifacts are rebuilt from source-of-truth state; agents may not treat them as canonical.

## Task contract

Every issue must state:

1. value hypothesis;
2. trust boundary touched;
3. invariants that may fall;
4. null/adversarial tests;
5. acceptance predicates;
6. forbidden changes;
7. rollback and data migration;
8. evidence expected from the verifier.

## Required output

- changed files and rationale;
- exact commands and environment;
- test, eval, mutation and migration results relevant to the change;
- unresolved uncertainty and non-executed gates;
- security/data-classification impact;
- rollback procedure.

## Fail-closed rules

- No placeholder `pass`, fake benchmark, invented citation or silent fallback.
- No authorization attribute from a request body.
- No retrieved text as system/tool instruction.
- No aggregate metric can hide leakage, stale authority or unsupported claims.
- A surviving critical mutant or failed invariant blocks merge.
- Coverage alone never authorizes merge.
