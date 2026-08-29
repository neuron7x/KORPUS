#!/usr/bin/env bash
# Commit only what this session changed, and only when the tree is green.
#
# Three commits today were pushed red. Twice because `make validate` ran in a compound
# command whose `&&` was consumed by an `echo` before `git commit`, and once because
# `git add -A ':!path'` excludes untracked paths only — a parallel session's edits to files
# git already tracks went in regardless, one of them 38 lines over its ceiling.
#
# Both are habits, and a habit is not a gate. This is.
#
#   scripts/guarded_commit.sh -m "message" -- path [path...]
#   GATES="validate api-test" scripts/guarded_commit.sh -F msg.txt -- path
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

commit_args=()
paths=()
seen_separator=0
for argument in "$@"; do
  if [ "$argument" = "--" ]; then seen_separator=1; continue; fi
  if [ "$seen_separator" -eq 1 ]; then paths+=("$argument"); else commit_args+=("$argument"); fi
done

if [ "${#paths[@]}" -eq 0 ]; then
  echo "refusing: name the paths this session changed, after --" >&2
  echo "\`git add -A\` with exclusions stages a parallel session's work too." >&2
  exit 64
fi

for target in ${GATES:-validate}; do
  echo "== make $target"
  if ! make "$target" >/dev/null 2>&1; then
    echo "refusing to commit: make $target failed" >&2
    make "$target" 2>&1 | tail -20 >&2
    exit 1
  fi
done

git add -- "${paths[@]}"
if git diff --cached --quiet; then
  echo "refusing: nothing staged from the named paths" >&2
  exit 65
fi
git diff --cached --name-only | sed 's/^/  staged /'
git commit "${commit_args[@]}"
