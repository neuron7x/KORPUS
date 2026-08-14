#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
python_bin="${PYTHON:-python3}"
shards="${KORPUS_MUTATION_SHARDS:-6}"
# Each mutant works in its own copy of the tree, so concurrency inside a shard
# changes wall-clock and nothing else. Without it the gate takes long enough that
# it gets run at the end of the work instead of during it.
jobs="${KORPUS_MUTATION_JOBS:-2}"
if ! [[ "$shards" =~ ^[1-9][0-9]*$ ]]; then
  echo "KORPUS_MUTATION_SHARDS must be a positive integer" >&2
  exit 2
fi
pids=()
for ((index=0; index<shards; index++)); do
  PYTHONPATH="${PYTHONPATH:-$root/apps/api/src}" "$python_bin" scripts/run_mutation_tests.py \
    --shard-index "$index" --shard-count "$shards" --jobs "$jobs" \
    >"var/mutation-shard-${index}.log" 2>&1 &
  pids+=("$!")
done
failed=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    failed=1
  fi
done
if [[ "$failed" -ne 0 ]]; then
  # A failed run must not leave the previous report in place. It did on 2026-08-05: six
  # mutants went INVALID after their targets moved to audit_reader.py, the run exited 1,
  # and var/mutation-report.json stayed behind from the run before. The operational gate
  # then read a report from a different tree and said "generated from a different source
  # tree" — true, and three steps from the actual cause. Absent evidence and stale
  # evidence must not be the same state.
  rm -f "$root/var/mutation-report.json" "$root/var/snapshot-mutation-report.json"
  echo "one or more mutation shards failed; removed stale mutation reports" >&2
  for ((index=0; index<shards; index++)); do
    echo "--- shard $index ---" >&2
    tail -80 "var/mutation-shard-${index}.log" >&2 || true
  done
  exit 1
fi
PYTHONPATH="${PYTHONPATH:-$root/apps/api/src}" "$python_bin" scripts/run_mutation_tests.py --merge --shard-count "$shards"
# Cross-layer temporal snapshot invariants have their own surgical destruction set.
# Keep it in the same `mutation` target so the assurance job cannot report a green
# mutation gate while issue #23's pre/post-read, cache-epoch, release-width, or
# semantic-epoch controls are untested.
PYTHONPATH="${PYTHONPATH:-$root/apps/api/src}" PYTHON="$python_bin" \
  "$python_bin" scripts/run_snapshot_mutation_tests.py
