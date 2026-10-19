# GitHub repository policy

## Authority

GitHub is the sole collaboration, CI, and merge authority for the current release line (`v0.9.7`).
Repository scripts, manifests, tests, and release identity remain the semantic source of
truth. GitLab is retained as a read-only provenance archive and must not become a second
policy implementation or delivery surface.

## Enforced repository settings

These settings live outside Git. Their measured state is recorded in
`docs/operations/GITHUB_DEVELOPMENT_READINESS.json`; source text alone is not evidence:

1. Default branch: `main`.
2. Require pull requests before merge; prohibit direct pushes to `main`.
3. Require the status checks emitted by `ci`, `assurance`, and `dependency-review`.
4. Require branches to be up to date before merge.
5. Dismiss stale approvals when the diff changes and require conversation resolution.
6. Enable secret scanning and push protection when the repository/plan supports them.
7. Enable code scanning/default CodeQL setup for supported languages.
8. Prevent force pushes and branch deletion on `main`.
9. Keep Actions workflow permissions read-only by default; grant write permissions only
   in workflows that require them.
10. Require signed release provenance verification for distributed ZIP artifacts.

The canonical owner observed from GitHub is `@neuron7x`; `.github/CODEOWNERS` records
review intent. A sole-owner repository cannot truthfully claim independent human review,
so the merge policy requires a pull request and resolved conversations but not a
fabricated second approver. Independent verification remains an evidence predicate.

## Required checks encoded in source

- `.github/workflows/ci.yml`: repository, API, quality, and web gates.
- `.github/workflows/assurance.yml`: falsification/mutation campaign and PostgreSQL suite.
- `.github/workflows/dependency-review.yml`: rejects newly introduced vulnerable dependencies.
- `.github/workflows/release.yml`: tag-bound package construction and signed provenance.
- `scripts/validate_github_actions.py`: rejects mutable action refs, mutable hosted-runner
  aliases, implicit permissions, missing timeouts, persisted checkout credentials, and
  privileged PR triggers.

## Fail-closed boundary

GitHub-hosted CI is not evidence for production secrets, live cluster reconciliation,
external red-team execution, risk-owner authorization, or production exact-environment
attestation. Those gates remain external and cannot be promoted by a green pull request.
