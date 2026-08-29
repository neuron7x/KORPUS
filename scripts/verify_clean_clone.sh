#!/usr/bin/env bash
# Run the gates where the author's disk cannot help them.
#
# Four separate defects this session were invisible in the working tree and obvious in a
# clone of HEAD: a digest counting untracked files, a catalog citing 52 captures the commit
# did not carry, a manifest describing a file a parallel session had since rewritten, and a
# module budget red on a commit already pushed. Each one passed `make validate` here and
# failed there.
#
# The clone is cheap (`--no-local` copies objects, seconds) and it answers one question the
# working tree cannot: does the commit stand on its own.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-${TMPDIR:-/tmp}/korpus-clean-clone-$$}"
# `validate` alone leaves the tests out, and a fixture or test datum that exists only in
# the working tree would pass it. api-test is the cheapest target that reads those files.
# mutation stays out on purpose: eleven minutes per commit does not pay for itself here.
TARGETS="${GATES:-validate api-test}"

rm -rf "$TARGET"
git clone --quiet --no-local "$ROOT" "$TARGET"
# The virtualenv is not in the commit and does not need to be: it is the interpreter, not
# the artefact under test.
ln -s "$ROOT/apps/api/.venv" "$TARGET/apps/api/.venv"

echo "clean clone of $(git -C "$ROOT" rev-parse --short HEAD) at $TARGET"
status=0
make -C "$TARGET" $TARGETS || status=$?
if [ "$status" -ne 0 ]; then
  echo "FAIL: the commit does not stand on its own — $TARGETS failed in a clean clone" >&2
  echo "The working tree passing here means the difference is untracked or uncommitted." >&2
fi
exit "$status"
