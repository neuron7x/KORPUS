#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

# Bind every packaging Git read to the same trusted object store as the source gate.
while IFS= read -r key; do
  [[ "$key" == GIT_* ]] && unset "$key"
done < <(compgen -e)
export GIT_NO_REPLACE_OBJECTS=1 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_SYSTEM=/dev/null GIT_ATTR_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0
git_bin="$(python3 -c 'from scripts.trusted_system_tools import git_executable; print(git_executable() or "")')"
[[ -n "$git_bin" ]] || { echo "trusted git executable unavailable" >&2; exit 1; }
git() { "$git_bin" --no-replace-objects "$@"; }


default_version="$(python3 -c 'import sys; sys.path.insert(0, "scripts"); from release_identity import release_tag; print(release_tag())')"
version="${KORPUS_RELEASE_VERSION:-$default_version}"
default_name="$(python3 -c 'import sys; sys.path.insert(0, "scripts"); from release_identity import load_release_identity; print(load_release_identity()["artifact_stem"])')"
name="${KORPUS_PACKAGE_NAME:-$default_name}"
python3 -c 'import sys; sys.path.insert(0, "scripts"); from package_identity_contract import safe_artifact_stem; raise SystemExit(not safe_artifact_stem(sys.argv[1]))' "$name" || { echo "invalid package name" >&2; exit 1; }
current_head="$(git rev-parse HEAD)"
source_commit="${KORPUS_PACKAGE_SOURCE_COMMIT:-$current_head}"
[[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid package source commit" >&2; exit 1; }
[[ "$current_head" == "$source_commit" ]] || { echo "package source commit is not current HEAD" >&2; exit 1; }

mkdir -p dist
rm -f "dist/${name}.zip" "dist/${name}.zip.sha256"
python3 "$root/scripts/check_release_identity.py"
python3 "$root/scripts/verify_source_manifest.py"

# Fail closed before admitting local evidence that could have read dirty source.
python3 "$root/scripts/check_clean_source_tree.py"

# 05.09.2026: тут стояла гілка `KORPUS_ENGINEERING_CANDIDATE=1`, яка МИНАЛА цю перевірку
# і авторизувала пакування з двох полів `CANONICAL_RELEASE_REPORT.json`. Той файл не пише
# ЖОДЕН крок: grep по дереву знаходить самих читачів, а введений він рукою одним комітом
# 348ecc56. Тому його `status` нефальсифіковний — немає дороги, якою він став би іншим.
# Його ж `source_tree_sha256` не збігається З ЖОДНИМ із двох доменів дайджеста на тому
# самому коміті (виміряно: evidence_paths 7ba9a8a1, tracked_tree 52fb2d2a проти e7ce416b),
# тож і прив'язки до дерева там немає. Змінну не виставляв ніхто в репозиторії — гілка
# лише чекала на того, хто її виставить. Лишилась одна дорога, і вона міряє.
PYTHONPATH="$root/scripts" python3 "$root/scripts/verify_release_evidence.py"

# Recheck source parity immediately before packaging, after evidence admission.
python3 "$root/scripts/check_clean_source_tree.py"

tmp="$(mktemp -d)"
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT INT TERM

# Freeze exactly one committed source revision. No .git, branches, refs or deleted blobs.
git archive --format=tar "$source_commit" | tar -xf - -C "$tmp"
# The archived v2 build metadata is part of the immutable source claim.
# Never overwrite it with a legacy v1 receipt or an invented gitless commit.
python3 "$root/scripts/verify_package_build_identity.py" --root "$tmp" > /dev/null

if [[ -d reports ]]; then
  rm -rf "$tmp/reports"
  cp -a reports "$tmp/reports"
fi
for artifact in source-sbom.cdx.json api-sbom.cdx.json web-sbom.cdx.json; do
  [[ -f "$artifact" ]] && cp "$artifact" "$tmp/$artifact"
done
find "$tmp" -type f -path '*/infra/secrets/*.txt' -delete

# A tracked bundle is source-digest-eligible, but must never enter a release archive.
if python3 - "$tmp" <<'PY'
import sys
from pathlib import Path

from scripts.git_bundle_policy import is_bundle_path

files = Path(sys.argv[1]).rglob("*")
raise SystemExit(not any(is_bundle_path(item) for item in files))
PY
then
  echo "history bundle forbidden in canonical package" >&2
  exit 1
fi

# Opaque local runtime evidence is not authenticated by source package verification.
if [[ -e "$tmp/evidence" ]]; then
  echo "unverified runtime evidence forbidden in canonical package" >&2
  exit 1
fi

cat > "$tmp/PACKAGE_BOUNDARY.md" <<'DOC'
# Що в цьому пакеті

Це один перевірюваний clean-source distribution artifact: exact committed source,
copied reports (not independently authenticated as a set), selected SBOMs and
manifests. `DISTRIBUTION_MANIFEST.json` описує точні байти архіву;
`SOURCE_MANIFEST.json` — canonical source boundary.

## Навмисно не включено

- `.git`, branches, refs, pull-request lineage та deleted historical blobs;
- unverified runtime registries (`var/evidence`, `var/releases`);
- production secrets та credentials;
- приватний/обмежений corpus payload;
- production authorization або зовнішня атестація, якщо вони не були реально отримані.

Відсутність production-only evidence не маскується як PASS. `PACKAGE_BUILD.json`
прив'язаний до `SOURCE_MANIFEST.json` і не приписує gitless архіву власного Git
commit. Git SHA належить лише зовнішньому provenance поточного CI.
DOC

python3 "$root/scripts/verify_package_build_identity.py" --root "$tmp" > /dev/null
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
