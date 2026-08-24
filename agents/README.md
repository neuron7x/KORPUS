# Agent lanes

Use `scripts/create_agent_worktree.sh ISSUE_ID AGENT SLUG` to create isolated branches.

Recommended lanes:

- `codex`: implementation and test expansion;
- `claude`: independent review, threat analysis, documentation consistency;
- `human`: scope, corpus authority, risk acceptance, merge decision.

Switch implementation/review agents between issues to prevent fixed-role bias. Never share production tokens through prompts or repository files.
