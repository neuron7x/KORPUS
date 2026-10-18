#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
[[ "$#" -le 1 ]] || { echo "usage: package_production_release.sh [--check-authority]" >&2; exit 2; }
[[ "$#" -eq 0 || "${1:-}" == "--check-authority" ]] || { echo "unknown argument: ${1:-}" >&2; exit 2; }
check_authority_only=false
if [[ "${1:-}" == "--check-authority" ]]; then
  check_authority_only=true
fi
readonly canonical_repository="neuron7x/KORPUS"
readonly canonical_repository_id="1332311807"
readonly canonical_owner_id="206596321"
: "${GITHUB_ACTIONS:?production release is permitted only in GitHub Actions}"
[[ "$GITHUB_ACTIONS" == "true" ]] || { echo "production release requires GitHub Actions" >&2; exit 1; }
: "${GITHUB_EVENT_NAME:?GitHub event name is required}"
[[ "$GITHUB_EVENT_NAME" == "push" ]] || { echo "production release requires a tag push event" >&2; exit 1; }
: "${GITHUB_SERVER_URL:?GitHub server identity is required}"
[[ "$GITHUB_SERVER_URL" == "https://github.com" ]] || { echo "production release requires github.com" >&2; exit 1; }
: "${GITHUB_REPOSITORY:?GitHub repository identity is required}"
[[ "$GITHUB_REPOSITORY" == "$canonical_repository" ]] || { echo "production release requires the canonical GitHub repository" >&2; exit 1; }
: "${GITHUB_REPOSITORY_ID:?immutable GitHub repository id is required}"
[[ "$GITHUB_REPOSITORY_ID" == "$canonical_repository_id" ]] || { echo "GitHub repository id is not canonical" >&2; exit 1; }
: "${GITHUB_REPOSITORY_OWNER_ID:?immutable GitHub owner id is required}"
[[ "$GITHUB_REPOSITORY_OWNER_ID" == "$canonical_owner_id" ]] || { echo "GitHub owner id is not canonical" >&2; exit 1; }
: "${RUNNER_ENVIRONMENT:?GitHub runner environment is required}"
[[ "$RUNNER_ENVIRONMENT" == "github-hosted" ]] || { echo "production release requires a GitHub-hosted runner" >&2; exit 1; }
[[ "${GITLAB_CI:-}" != "true" ]] || { echo "legacy GitLab CI cannot authorize a production release" >&2; exit 1; }
: "${GITHUB_REF_PROTECTED:?protected-ref status is required}"
[[ "$GITHUB_REF_PROTECTED" == "true" ]] || { echo "production release requires a protected GitHub ref" >&2; exit 1; }
: "${GITHUB_REF_TYPE:?GitHub ref type is required}"
[[ "$GITHUB_REF_TYPE" == "tag" ]] || { echo "production release requires a tag ref" >&2; exit 1; }
: "${GITHUB_REF_NAME:?GitHub ref name is required}"
: "${GITHUB_REF:?GitHub ref is required}"
: "${GITHUB_SHA:?GitHub source SHA is required}"
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "GitHub source SHA is not a full commit identifier" >&2; exit 1; }
: "${GITHUB_WORKFLOW_REF:?GitHub workflow identity is required}"
: "${GITHUB_RUN_ID:?GitHub run id is required}"
: "${GITHUB_RUN_ATTEMPT:?GitHub run attempt is required}"
[[ "$GITHUB_RUN_ID" =~ ^[0-9]+$ && "$GITHUB_RUN_ATTEMPT" =~ ^[0-9]+$ ]] || { echo "GitHub run identity is invalid" >&2; exit 1; }
expected_tag="$(python3 -c 'import sys; sys.path.insert(0,"scripts"); from release_identity import release_tag; print(release_tag())')"
expected_ref="refs/tags/${expected_tag}"
expected_workflow_ref="${canonical_repository}/.github/workflows/release.yml@${expected_ref}"
[[ "$GITHUB_REF_NAME" == "$expected_tag" ]] || { echo "GitHub tag does not match canonical release identity" >&2; exit 1; }
[[ "$GITHUB_REF" == "$expected_ref" ]] || { echo "GitHub ref does not match canonical release identity" >&2; exit 1; }
[[ "$GITHUB_WORKFLOW_REF" == "$expected_workflow_ref" ]] || { echo "release did not originate from the canonical GitHub workflow" >&2; exit 1; }
head_sha="$(git rev-parse --verify 'HEAD^{commit}')"
event_sha="$(git rev-parse --verify "${GITHUB_SHA}^{commit}")"
tag_sha="$(git rev-parse --verify "refs/tags/${expected_tag}^{commit}")"
main_sha="$(git rev-parse --verify 'refs/remotes/origin/main^{commit}')"
[[ "$event_sha" == "$head_sha" ]] || { echo "checked-out HEAD differs from the GitHub event SHA" >&2; exit 1; }
[[ "$tag_sha" == "$head_sha" ]] || { echo "release tag does not resolve to checked-out HEAD" >&2; exit 1; }
git merge-base --is-ancestor "$head_sha" "$main_sha" || { echo "release commit is not contained in canonical GitHub main" >&2; exit 1; }
[[ "$check_authority_only" == false ]] || exit 0
: "${KORPUS_RELEASE_SIGNING_KEY:?KORPUS_RELEASE_SIGNING_KEY must point to an external Ed25519 private key}"
: "${KORPUS_HOSTED_BUILDER_SIGNING_KEY:?hosted-builder Ed25519 signing key is required}"
: "${KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256:?production-assurance trust root is required}"
: "${KORPUS_TRUSTED_HOSTED_BUILDER_SIGNER_SHA256:?hosted-builder trust root is required}"
: "${KORPUS_TRUSTED_RELEASE_SIGNER_SHA256:?release trust root is required}"
: "${KORPUS_TRUSTED_BUILDER_ID:?trusted hosted builder id is required}"
expected_builder_id="https://github.com/${canonical_repository}/.github/workflows/release.yml@${expected_ref}"
[[ "$KORPUS_TRUSTED_BUILDER_ID" == "$expected_builder_id" ]] || { echo "builder id is not the canonical GitHub release workflow" >&2; exit 1; }
for key in "$KORPUS_RELEASE_SIGNING_KEY" "$KORPUS_HOSTED_BUILDER_SIGNING_KEY"; do
  [[ -f "$key" && ! -L "$key" ]] || { echo "release signing key must be a regular file" >&2; exit 1; }
done
[[ "$KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256" != "$KORPUS_TRUSTED_RELEASE_SIGNER_SHA256" ]] || { echo "production-assurance and release trust roots must differ" >&2; exit 1; }
[[ "$KORPUS_TRUSTED_HOSTED_BUILDER_SIGNER_SHA256" != "$KORPUS_TRUSTED_RELEASE_SIGNER_SHA256" ]] || { echo "hosted-builder and release trust roots must differ" >&2; exit 1; }
[[ "$KORPUS_TRUSTED_HOSTED_BUILDER_SIGNER_SHA256" != "$KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256" ]] || { echo "hosted-builder and assurance trust roots must differ" >&2; exit 1; }
python3 scripts/check_release_identity.py --require-git-tag
PYTHONPATH=apps/api/src:scripts python3 scripts/verify_production_assurance.py
scripts/package_repository.sh
name="$(python3 -c 'import sys; sys.path.insert(0,"scripts"); from release_identity import load_release_identity; print(load_release_identity()["artifact_stem"])')"
artifact="dist/${name}.zip"
manifest="dist/${name}.release-manifest.json"
attestation="dist/${name}.release-attestation.json"
builder_provenance="dist/${name}.builder-provenance.json"
builder_attestation="dist/${name}.builder-attestation.json"
final_authorization="dist/${name}.final-production-authorization.json"
invocation_id="https://github.com/${canonical_repository}/actions/runs/${GITHUB_RUN_ID}/attempts/${GITHUB_RUN_ATTEMPT}"
PYTHONPATH=apps/api/src:scripts python3 scripts/slsa_provenance.py generate --artifact "$artifact" --out "$builder_provenance" --builder-id "$KORPUS_TRUSTED_BUILDER_ID" --invocation-id "$invocation_id"
python3 scripts/release_attestation.py sign --manifest "$builder_provenance" --key "$KORPUS_HOSTED_BUILDER_SIGNING_KEY" --out "$builder_attestation"
python3 - "$artifact" "$manifest" <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path
artifact, out = map(Path, sys.argv[1:])
root = Path.cwd()
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
release = json.loads((root/'apps/api/src/korpus/release.json').read_text())
payload = {
  'schema': 'korpus.signed-release-manifest.v1',
  'release': release['tag'],
  'git_commit': subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip(),
  'artifact': artifact.name,
  'artifact_sha256': sha(artifact),
  'source_manifest_sha256': sha(root/'SOURCE_MANIFEST.json'),
  'production_assurance_sha256': sha(root/'reports/PRODUCTION_ASSURANCE_REPORT.json'),
}
out.write_text(json.dumps(payload, sort_keys=True, separators=(',', ':'))+'\n')
PY
python3 scripts/release_attestation.py sign --manifest "$manifest" --key "$KORPUS_RELEASE_SIGNING_KEY" --out "$attestation"
python3 scripts/release_attestation.py verify --manifest "$manifest" --attestation "$attestation" --trust-config config/assurance/trusted-assurance-signers.json --trust-field release_ed25519_public_key_sha256 --trust-env KORPUS_TRUSTED_RELEASE_SIGNER_SHA256 --require-trusted
PYTHONPATH=apps/api/src:scripts python3 scripts/verify_final_release_authorization.py \
  --artifact "$artifact" --release-manifest "$manifest" --release-attestation "$attestation" \
  --builder-provenance "$builder_provenance" --builder-attestation "$builder_attestation" \
  --out "$final_authorization"
sha256sum "$artifact" "$manifest" "$attestation" "$builder_provenance" "$builder_attestation" "$final_authorization" > "dist/${name}.production.sha256"
printf '%s\n' "$artifact" "$manifest" "$attestation" "$builder_provenance" "$builder_attestation" "$final_authorization"
