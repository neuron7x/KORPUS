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
# Клон СПОЧАТКУ виробляє докази, потім їх перевіряє. `validate` містить
# `evidence-freshness`, а в свіжому клоні `var/` порожня — усі звіти ВІДСУТНІ, і гейт
# відмовляє правильно. Виміряно 03.09.2026: ця відмова була латентною, бо
# `verify-clean-clone` живе в `check-nightly`, який до цієї сесії не виконувався жодного
# разу. Питання, на яке відповідає клон, — «чи стоїть коміт САМ ПО СОБІ», і воно включає
# «чи вміє він виробити власні докази».
#
# `mutation` ТЕПЕР У НАБОРІ, і це зміна попереднього рішення. Причина не в тому, що
# одинадцять хвилин стали дешевшими: ланцюг замкнувся. `validate` містить
# `evidence-freshness`, той вимагає свіжого `operational-gate`, а той читає
# `var/mutation-report.json`. Виключити мутацію означало б лишити клон падати на
# відсутньому звіті — тобто мати ціль, яка не може пройти ніколи.
#
# Ціна прийнятна саме тут: `verify-clean-clone` живе в `check-nightly`, лані, який і
# створений для дорогого за побудовою. У `check` цього набору немає.
TARGETS="${GATES:-eval migration-gate scale mutation operational-gate validate api-test}"

rm -rf "$TARGET"
git clone --quiet --no-local "$ROOT" "$TARGET"
# The virtualenv is not in the commit and does not need to be: it is the interpreter, not
# the artefact under test.
ln -s "$ROOT/apps/api/.venv" "$TARGET/apps/api/.venv"

COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
echo "clean clone of ${COMMIT:0:8} at $TARGET"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
status=0
make -C "$TARGET" $TARGETS || status=$?

# Звіт пишеться ЗАВЖДИ, і в цьому весь сенс. Вимір, чий результат нікуди не лягає, не є
# виміром: споживач читає файл від попереднього прогону й не має способу дізнатись, що
# вимір узагалі був. Той самий клас щойно знайдено в `gate-liveness`, який писав звіт
# лише за наявності `OUT=`.
REPORT="${CLEAN_CLONE_REPORT:-$ROOT/var/clean-clone.json}"
mkdir -p "$(dirname "$REPORT")"
cat > "$REPORT" <<JSON
{
  "schema": "korpus.clean-clone.v1",
  "status": "$([ "$status" -eq 0 ] && echo PASS || echo FAIL)",
  "commit": "$COMMIT",
  "targets": "$TARGETS",
  "exit_code": $status,
  "started_at": "$started",
  "finished_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "interpretation": "Клон HEAD без робочого дерева. Відповідає на питання, якого робоче дерево поставити не може: чи стоїть коміт сам по собі. Мутація сюди НЕ входить навмисно — одинадцять хвилин на коміт тут не окупаються."
}
JSON

if [ "$status" -ne 0 ]; then
  echo "FAIL: the commit does not stand on its own — $TARGETS failed in a clean clone" >&2
  echo "The working tree passing here means the difference is untracked or uncommitted." >&2
fi
exit "$status"
