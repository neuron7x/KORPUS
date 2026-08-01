#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
version="${KORPUS_RELEASE_VERSION:-v4.0.0}"
name="korpus-infrastructure-hardened-${version}"
mkdir -p dist
rm -f "dist/${name}.zip" "dist/${name}.zip.sha256"
PYTHONPATH="$root/scripts" python3 "$root/scripts/verify_release_evidence.py"

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
python3 "$root/scripts/generate_manifest.py" "$tmp"
cp "$tmp/REPOSITORY_MANIFEST.json" "$root/REPOSITORY_MANIFEST.json"
(
  cd "$tmp"
  find . -type f -print0 | LC_ALL=C sort -z | xargs -0 touch -h -d '@0'
  LC_ALL=C find . -type f -print | LC_ALL=C sort | zip -X -q "$root/dist/${name}.zip" -@
)
sha256sum "dist/${name}.zip" > "dist/${name}.zip.sha256"
cat "dist/${name}.zip.sha256"
