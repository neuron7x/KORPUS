#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 3 ]]; then
  echo "usage: $0 ISSUE_ID AGENT SLUG" >&2
  exit 64
fi
issue="$1"; agent="$2"; slug="$3"
branch="${agent}/issue-${issue}-${slug}"
root="$(git rev-parse --show-toplevel)"
worktree="${root}/../$(basename "$root")-${agent}-${issue}"
git fetch --all --prune
git worktree add -b "$branch" "$worktree" origin/main
printf 'branch=%s\nworktree=%s\n' "$branch" "$worktree"
