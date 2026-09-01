#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

default_version="$(python3 -c 'import sys; sys.path.insert(0, "scripts"); from release_identity import release_tag; print(release_tag())')"
version="${KORPUS_RELEASE_VERSION:-$default_version}"
default_name="$(python3 -c 'import sys; sys.path.insert(0, "scripts"); from release_identity import load_release_identity; print(load_release_identity()["artifact_stem"])')"
name="${KORPUS_PACKAGE_NAME:-$default_name}"
current_head="$(git rev-parse HEAD)"
source_commit="${KORPUS_PACKAGE_SOURCE_COMMIT:-$current_head}"
[[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid package source commit" >&2; exit 1; }
[[ "$current_head" == "$source_commit" ]] || { echo "package source commit is not current HEAD" >&2; exit 1; }

mkdir -p dist
rm -f "dist/${name}.zip" "dist/${name}.zip.sha256"
python3 "$root/scripts/check_release_identity.py"
python3 "$root/scripts/verify_source_manifest.py"

# Research evidence is mandatory for a formal research release. A canonical engineering
# candidate may carry an explicit release report instead; production-release remains stricter.
if [[ "${KORPUS_ENGINEERING_CANDIDATE:-0}" == "1" ]]; then
  [[ -f reports/CANONICAL_RELEASE_REPORT.json ]] || { echo "canonical release report missing" >&2; exit 1; }
  python3 - <<'PY'
import json
from pathlib import Path
p=json.loads(Path('reports/CANONICAL_RELEASE_REPORT.json').read_text())
if p.get('engineering_release_candidate') is not True or p.get('status') not in {'PASS_WITH_CAVEATS','PASS'}:
    raise SystemExit('canonical release report does not authorize engineering candidate packaging')
PY
else
  PYTHONPATH="$root/scripts" python3 "$root/scripts/verify_release_evidence.py"
fi

tmp="$(mktemp -d)"
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT INT TERM

# Freeze exactly one committed source revision. No .git, branches, refs or deleted blobs.
git archive --format=tar "$source_commit" | tar -xf - -C "$tmp"
printf '{"schema":"korpus.package-build.v1","source_commit":"%s","release":"%s","history_included":false}\n' \
  "$source_commit" "$version" > "$tmp/PACKAGE_BUILD.json"

if [[ -d reports ]]; then
  rm -rf "$tmp/reports"
  cp -a reports "$tmp/reports"
fi
for artifact in source-sbom.cdx.json api-sbom.cdx.json web-sbom.cdx.json; do
  [[ -f "$artifact" ]] && cp "$artifact" "$tmp/$artifact"
done
find "$tmp" -type f -path '*/infra/secrets/*.txt' -delete

if [[ -d var/evidence ]]; then
  mkdir -p "$tmp/evidence"
  cp -a var/evidence/. "$tmp/evidence/"
fi
if [[ -d var/releases ]]; then
  mkdir -p "$tmp/evidence/releases"
  cp -a var/releases/. "$tmp/evidence/releases/"
fi

cat > "$tmp/PACKAGE_BOUNDARY.md" <<'DOC'
# Що в цьому пакеті

Це один перевірюваний clean-source distribution artifact: exact committed source,
release reports, selected evidence and manifests. `DISTRIBUTION_MANIFEST.json` описує
точні байти архіву; `SOURCE_MANIFEST.json` — canonical source boundary.

## Навмисно не включено

- `.git`, branches, refs, pull-request lineage та deleted historical blobs;
- production secrets та credentials;
- приватний/обмежений corpus payload;
- production authorization або зовнішня атестація, якщо вони не були реально отримані.

Відсутність production-only evidence не маскується як PASS. `PACKAGE_BUILD.json` зв'язує
архів з одним commit source tree. Старі гілки не є частиною release payload.
DOC

[[ "$(git rev-parse HEAD)" == "$source_commit" ]] || { echo "HEAD moved before manifest construction" >&2; exit 1; }
python3 "$root/scripts/generate_manifest.py" "$tmp" --kind distribution --output "$tmp/DISTRIBUTION_MANIFEST.json"
(
  cd "$tmp"
  find . -type f -print0 | LC_ALL=C sort -z | xargs -0 touch -h -d '@0'
  LC_ALL=C find . -type f -print | LC_ALL=C sort | zip -X -q "$root/dist/${name}.zip" -@
)
[[ "$(git rev-parse HEAD)" == "$source_commit" ]] || { echo "HEAD moved during package construction" >&2; exit 1; }
sha256sum "dist/${name}.zip" > "dist/${name}.zip.sha256"
# Ім'я архіву має ОДНЕ джерело — `release_identity`. Хто перевіряє архів далі, читає
# його звідси, а не обчислює вдруге: друга копія правила розійшлася б мовчки.
printf '%s\n' "dist/${name}.zip" > "dist/LATEST"
python3 "$root/scripts/verify_package.py" "dist/${name}.zip"
cat "dist/${name}.zip.sha256"
