# GitHub repository policy

## Authority

GitHub becomes the primary collaboration and CI transport for the `v0.1.x` line.
Repository scripts, manifests, tests, and release identity remain the semantic source of
truth. The retained GitLab pipeline is a legacy parity/evidence surface during migration;
it must not become a second policy implementation.

## Required repository settings after import

These settings live outside Git and therefore cannot be truthfully marked PASS by this
package. Configure them on the GitHub repository before treating `main` as protected:

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

Repository-owner/CODEOWNERS identity is intentionally not fabricated in source. Add a
valid `.github/CODEOWNERS` only after the canonical GitHub owner/team is known; an
invented handle would create a control that appears configured but is not enforceable.
The canonical owner is now observed as `@neuron7x`, so `.github/CODEOWNERS` records
review intent. On 2026-08-12 GitHub returned `403` when branch protection was queried
for this private repository because the account requires GitHub Pro or public visibility
for that feature. Therefore CODEOWNERS review is **not an enforced merge predicate** in
the current external state. `docs/operations/GITHUB_DEVELOPMENT_READINESS.json` records
that blocker, and no document may describe `main` as protected until a later API
observation proves it.

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
