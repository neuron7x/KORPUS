#!/usr/bin/env bash
# Run every scanner the pipeline declares, here, and leave the reports behind.
#
# SUP-005: the pipeline declared gitleaks, pip-audit and trivy, and the audit recorded
# that none of them had been executed in the environment being audited. A declared
# scanner is a plan; an archived report with an exit code is evidence. The difference
# matters because the pipeline had never run on this tree at all — GitLab CI quota has
# been exhausted every month since the project started.
#
# Every scanner runs even if an earlier one fails, because "the first scanner found
# something" is a bad reason to learn nothing about the other two. The exit code is the
# worst of them.
#
#   make security-scan
set -uo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
cd "$root"

out="${KORPUS_SECURITY_REPORT_DIR:-var/security}"
mkdir -p "$out"
worst=0
# НЕ `summary.json`: цей файл — доказ від сканерів, що бігли у ЗАКРІПЛЕНИХ образах
# конвеєра, і його збирає `aggregate_ci_security_summary.py` зі схемою 2 та комітом.
# Виміряно 06.09.2026: цей скрипт писав туди ж схему 1 без коміта, тихо ПІДМІНЮЮЧИ
# сильніший клас доказу слабшим під тим самим іменем — і сьомий твердий предикат упав
# від власної батареї. Локальний прогін пише поруч і називає себе.
summary="$out/local-summary.json"

note() { printf '%s\n' "$*" >&2; }
record() {
  local name="$1" code="$2"
  printf '  %-12s exit %s\n' "$name" "$code" >&2
  [[ "$code" -gt "$worst" ]] && worst="$code"
  printf '{"scanner":"%s","exit_code":%s}\n' "$name" "$code" >> "$out/.results"
}

: > "$out/.results"

# Secrets, across history rather than the working tree: a credential that was committed
# and then deleted is still in the pack files and still on every clone.
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --source . --no-banner --redact --exit-code 1 \
    --baseline-path .gitleaks-baseline.json --report-path "$out/gitleaks.json" \
    > "$out/gitleaks.log" 2>&1
  record gitleaks $?
else
  note "gitleaks is not installed; the secret scan did not run"
  record gitleaks 127
fi

# Dependencies, from the lock files rather than the environment: the environment is what
# somebody happened to install, and the lock is what a deployment will get.
PY="${PY:-apps/api/.venv/bin/python}"
audit_python=""
for candidate in "$PY" python3; do
  if "$candidate" -m pip_audit --version 2>/dev/null | grep -qx 'pip-audit 2.10.1'; then
    audit_python="$candidate"
    break
  fi
done
if [[ -n "$audit_python" ]]; then
  for lock in runtime dev; do
    "$audit_python" -m pip_audit --strict --disable-pip --no-deps \
      -r "apps/api/requirements.$lock.lock" --format json \
      -o "$out/pip-audit-$lock.json" > "$out/pip-audit-$lock.log" 2>&1
    record "pip-audit:$lock" $?
  done
else
  note "pip-audit is not installed; the dependency audit did not run"
  record pip-audit 127
fi

# Filesystem: vulnerabilities, secrets and misconfiguration, with the one recorded
# exception honoured. `.trivyignore.yaml` scopes it to the file it was verified in, so
# the same rule firing anywhere else still fails.
if command -v trivy >/dev/null 2>&1; then
  trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL \
    --ignorefile .trivyignore.yaml --exit-code 1 \
    --skip-dirs 'apps/api/.venv,node_modules,var,.git' \
    --format json -o "$out/trivy-fs.json" --quiet . > "$out/trivy.log" 2>&1
  record trivy $?
else
  note "trivy is not installed; the filesystem scan did not run"
  record trivy 127
fi

python3 - "$out" "$summary" "$worst" <<'PY'
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

directory, summary, worst = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
commit = head.stdout.strip() if head.returncode == 0 else ""
results = [
    json.loads(line)
    for line in (directory / ".results").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
summary.write_text(
    json.dumps(
        {
            "schema_version": 1,
            "class": "LOCAL_SCANNERS",
            "ran_at": datetime.now(UTC).isoformat(),
            "commit_sha": commit,
            "scanners": results,
            "worst_exit_code": worst,
            # 127 is "the scanner is not installed", which is not a clean scan. Recording
            # it as its own value is the whole point: a summary that reported "no
            # findings" for a tool that never started is the failure this file exists
            # against.
            "status": "PASS" if worst == 0 else "FAIL",
            "interpretation": (
                "Exit codes from the scanners themselves, archived beside their reports. "
                "127 means the scanner was absent, which is neither a pass nor a finding "
                "— it is an unexecuted check, and it fails the summary."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(json.dumps(json.loads(summary.read_text(encoding="utf-8")), ensure_ascii=False, indent=2))
PY

rm -f "$out/.results"
exit "$worst"
