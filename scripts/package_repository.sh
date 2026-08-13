#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
default_version="$(python3 -c 'import sys; sys.path.insert(0, "scripts"); from release_identity import release_tag; print(release_tag())')"
version="${KORPUS_RELEASE_VERSION:-$default_version}"
# The artifact stem is release metadata, not an independent version declaration.
default_name="$(python3 -c 'import sys; sys.path.insert(0, "scripts"); from release_identity import load_release_identity; print(load_release_identity()["artifact_stem"])')"
name="${KORPUS_PACKAGE_NAME:-$default_name}"
mkdir -p dist
rm -f "dist/${name}.zip" "dist/${name}.zip.sha256"
python3 "$root/scripts/check_release_identity.py" --require-git-tag
PYTHONPATH="$root/scripts" python3 "$root/scripts/verify_release_evidence.py"
python3 "$root/scripts/verify_source_manifest.py"

tmp="$(mktemp -d)"
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT INT TERM

# The source tree is exactly the committed revision; generated evidence is copied explicitly.
git archive --format=tar HEAD | tar -xf - -C "$tmp"
if [[ -d reports ]]; then
  rm -rf "$tmp/reports"
  cp -a reports "$tmp/reports"
fi
for artifact in source-sbom.cdx.json api-sbom.cdx.json web-sbom.cdx.json; do
  [[ -f "$artifact" ]] && cp "$artifact" "$tmp/$artifact"
done
find "$tmp" -type f -path '*/infra/secrets/*.txt' -delete

# The sealed evidence registry and the frozen corpus release travel with the source.
# Without them the package is a system nobody can check: the reports that show what it
# does under load, when a dependency is broken, and against its own corpus all live in
# `var/`, which is cleaned, and in CI artefacts, which expire in weeks.
if [[ -d var/evidence ]]; then
  mkdir -p "$tmp/evidence"
  cp -a var/evidence/. "$tmp/evidence/"
fi
if [[ -d var/releases ]]; then
  mkdir -p "$tmp/evidence/releases"
  cp -a var/releases/. "$tmp/evidence/releases/"
fi

# Named explicitly rather than left for a reader to discover by its absence.
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
sha256sum "dist/${name}.zip" > "dist/${name}.zip.sha256"
python3 "$root/scripts/verify_package.py" "dist/${name}.zip"
cat "dist/${name}.zip.sha256"
