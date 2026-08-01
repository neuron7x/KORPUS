# KORPUS v5.1.0 — local agent handoff release

This release does not change production authorization. It adds a complete local handoff layer for Claude Code/Codex:

- factual current-state and work acts;
- completed iteration and integration ledgers;
- exact calibration/weights registry;
- test/assurance act;
- next 10 iterations and next 7 integrations;
- machine-readable task queues and acceptance gates;
- Linux runbook and agent/verifier master prompts;
- executable handoff consistency verifier and tests.

Base product semantics remain v5.0.0. Current status remains engineering baseline / controlled pilot only; production authorization is false.

Release provenance was additionally hardened: `generate_manifest.py` now includes only Git-tracked/staged files in a worktree and excludes local coverage artifacts; gitless archives still enumerate their complete snapshot. System/source manifests exclude generated `handoff/evidence/` to prevent evidence-source cycles.
