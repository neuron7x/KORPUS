#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
: "${GITLAB_CI:?production release is permitted only in GitLab CI}"
[[ "$GITLAB_CI" == "true" ]] || { echo "production release requires GitLab CI" >&2; exit 1; }
: "${CI_COMMIT_REF_PROTECTED:?protected-ref status is required}"
[[ "$CI_COMMIT_REF_PROTECTED" == "true" ]] || { echo "production release requires a protected ref" >&2; exit 1; }
: "${CI_COMMIT_TAG:?production release requires a tag pipeline}"
expected_tag="$(python3 -c 'import sys; sys.path.insert(0,"scripts"); from release_identity import release_tag; print(release_tag())')"
[[ "$CI_COMMIT_TAG" == "$expected_tag" ]] || { echo "CI tag does not match canonical release identity" >&2; exit 1; }
: "${KORPUS_RELEASE_SIGNING_KEY:?KORPUS_RELEASE_SIGNING_KEY must point to an external Ed25519 private key}"
: "${KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256:?production-assurance trust root is required}"
: "${KORPUS_TRUSTED_RELEASE_SIGNER_SHA256:?release trust root is required}"
[[ "$KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256" != "$KORPUS_TRUSTED_RELEASE_SIGNER_SHA256" ]] || { echo "production-assurance and release trust roots must differ" >&2; exit 1; }
python3 scripts/check_release_identity.py --require-git-tag
PYTHONPATH=apps/api/src:scripts python3 scripts/verify_production_assurance.py
source_commit="$(git rev-parse HEAD)"
KORPUS_PACKAGE_SOURCE_COMMIT="$source_commit" scripts/package_repository.sh
[[ "$(git rev-parse HEAD)" == "$source_commit" ]] || { echo "HEAD moved after package construction" >&2; exit 1; }
name="$(python3 -c 'import sys; sys.path.insert(0,"scripts"); from release_identity import load_release_identity; print(load_release_identity()["artifact_stem"])')"
artifact="dist/${name}.zip"
manifest="dist/${name}.release-manifest.json"
attestation="dist/${name}.release-attestation.json"
python3 scripts/release_artifact_manifest.py --artifact "$artifact" --out "$manifest" --expected-source-commit "$source_commit" --expected-release "$CI_COMMIT_TAG"
python3 scripts/release_attestation.py sign --manifest "$manifest" --key "$KORPUS_RELEASE_SIGNING_KEY" --out "$attestation"
python3 scripts/release_attestation.py verify --manifest "$manifest" --attestation "$attestation" --trust-config config/assurance/trusted-assurance-signers.json --trust-field release_ed25519_public_key_sha256 --trust-env KORPUS_TRUSTED_RELEASE_SIGNER_SHA256 --require-trusted
sha256sum "$artifact" "$manifest" "$attestation" > "dist/${name}.production.sha256"
printf '%s\n' "$artifact" "$manifest" "$attestation"
