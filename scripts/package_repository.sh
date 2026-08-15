#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
default_version="$(python3 -c 'import sys; sys.path.insert(0, "scripts"); from release_identity import release_tag; print(release_tag())')"
version="${KORPUS_RELEASE_VERSION:-$default_version}"
# The artifact stem is release metadata, not an independent version declaration.
default_name="$(python3 -c 'import sys; sys.path.insert(0, "scripts"); from release_identity import load_release_identity; print(load_release_identity()["artifact_stem"])')"
name="${KORPUS_PACKAGE_NAME:-$default_name}"
current_head="$(git rev-parse HEAD)"
source_commit="${KORPUS_PACKAGE_SOURCE_COMMIT:-$current_head}"
[[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid package source commit" >&2; exit 1; }
[[ "$current_head" == "$source_commit" ]] || { echo "package source commit is not current HEAD" >&2; exit 1; }
mkdir -p dist
rm -f "dist/${name}.zip" "dist/${name}.zip.sha256"
python3 "$root/scripts/check_release_identity.py" --require-git-tag
PYTHONPATH="$root/scripts" python3 "$root/scripts/verify_release_evidence.py"
python3 "$root/scripts/verify_source_manifest.py"

tmp="$(mktemp -d)"
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT INT TERM

# Freeze exactly one committed source revision. PACKAGE_BUILD.json is package-only
# metadata and therefore excluded from the source-manifest semantic boundary.
git archive --format=tar "$source_commit" | tar -xf - -C "$tmp"
printf '{"schema":"korpus.package-build.v1","source_commit":"%s"}\n' "$source_commit" > "$tmp/PACKAGE_BUILD.json"
if [[ -d reports ]]; then
  rm -rf "$tmp/reports"
  cp -a reports "$tmp/reports"
fi
for artifact in source-sbom.cdx.json api-sbom.cdx.json web-sbom.cdx.json; do
  [[ -f "$artifact" ]] && cp "$artifact" "$tmp/$artifact"
done
find "$tmp" -type f -path '*/infra/secrets/*.txt' -delete

# The sealed evidence registry and the frozen corpus release travel with the source.
# Git history deliberately does not: distributable confidentiality must not depend on
# repository-lifetime history or deleted blobs.
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

Це перевірюваний distribution artifact: current source snapshot, release reports,
sealed evidence registry та manifests. `DISTRIBUTION_MANIFEST.json` описує точні байти
архіву; `SOURCE_MANIFEST.json` — current source snapshot без generated assurance artifacts.

## Навмисно не включено

- Git history, branches, refs та deleted historical blobs;
- production secrets та credentials;
- приватний/обмежений corpus payload;
- production authorization, risk-owner signature або зовнішня атестація.

Git history не є частиною distribution provenance: current-source integrity доводять
source/distribution manifests та release evidence. Відсутність production-only material
не маскується як PASS. Поточні зовнішні залежності й допуски зафіксовані в
`docs/audit/closure/` та release assurance reports.
DOC
python3 "$root/scripts/generate_manifest.py" "$tmp" --kind distribution --output "$tmp/DISTRIBUTION_MANIFEST.json"
(
  cd "$tmp"
  find . -type f -print0 | LC_ALL=C sort -z | xargs -0 touch -h -d '@0'
  LC_ALL=C find . -type f -print | LC_ALL=C sort | zip -X -q "$root/dist/${name}.zip" -@
)
[[ "$(git rev-parse HEAD)" == "$source_commit" ]] || { echo "HEAD moved during package construction" >&2; exit 1; }
sha256sum "dist/${name}.zip" > "dist/${name}.zip.sha256"
python3 "$root/scripts/verify_package.py" "dist/${name}.zip"
cat "dist/${name}.zip.sha256"
