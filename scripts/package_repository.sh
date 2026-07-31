#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
mkdir -p dist
version="${KORPUS_RELEASE_VERSION:-v3.0.0}"
name="korpus-operational-reference-${version}"
rm -f "dist/${name}.zip" "dist/${name}.zip.sha256"
zip -X -q -r "dist/${name}.zip" . \
  -x '.git/*' 'dist/*' 'var/*' '*/node_modules/*' '*/.venv/*' '*/__pycache__/*' \
     '*/.pytest_cache/*' 'infra/secrets/*.txt' '*.pyc'
sha256sum "dist/${name}.zip" > "dist/${name}.zip.sha256"
cat "dist/${name}.zip.sha256"
