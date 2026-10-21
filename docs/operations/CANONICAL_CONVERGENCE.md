# Canonical convergence candidate (issue #89)

## Status and boundaries

This is a staged integration candidate, not an admitted main merge or production release.
It combines the pinned package/pilot/distribution stack and metadata-only validator.
No source material is fetched or indexed; no model, runtime, service or deployment is activated.
The existing main admission governance (#72), independent review and exact-head checks remain required.
The older SHA-specific PR #88 automatic merge pin is not changed by this candidate.

## Exact provenance

- Main: `345c0f7daf1da2152d0e554cc8733381ca5a1e9e`.
- Package stack (#82/#84/#85/#86/#87): `1d9329d8c08cc96ded90f8580017275267a6225f`.
- Metadata validator (#88): `1a79f590579422de28c6e5ff7997a3b1d9beb18e`.
- Branch graph evidence: GitHub run 39589417052, artifact 12341126308.
- Original branches: 39 = main + 25 already in main + 6 ahead + 7 diverged.
- The isolated audit/integration branch adds one observed branch; it is not hidden in the count.

The two source deltas overlap only in module-budget and source/package identity files.
Module budgets use a checked three-way union, preserving all source entries and historical reasons;
conflicting module edits fail rather than selecting a permissive maximum. Generated identities are
rebuilt from the actual combined staged source. Unchanged files retain their exact original Git blobs.
Temporary audit/producer workflows must not appear in the final candidate tree.

## Defensive corrections during integration

The package stack's existing complexity ceiling is restored without raising a budget:
normalized-empty path components use one set-membership predicate. Structural file/directory
sets use the same normalized namespace as alias detection. Prefix checks include explicit
nested directory entries as well as files. New tests operate only on inert ZipInfo metadata;
they never extract archive data or probe a remote target. They preserve ordinary distinct paths.

A passing focused suite is not a substitute for full PostgreSQL/API/web/research/contract CI.
Mutation controls substantiate named finite properties, not universal exploit resistance.
Existing warnings, conditional test skips, release-signing obligations and any uncovered behavior
must remain visible rather than being relabelled as solved.

## Branch disposition

Twenty-five branch tips are already ancestors of main and require no repeated merge.
The package stack ancestry is represented once; do not independently merge its component PRs
and the same aggregate. The standalone audit/pr85-empty-component-fix-20261021 tip is retained
until its auxiliary history is reconciled. The seven divergent tips are not blindly imported:

| Branch | Exact observed head | Ahead / behind main | Disposition |
| --- | --- | --- | --- |
| `agent/ci-local-ref-isolation-20261018` | `df008029c6d630bdbe825cacd214715a95337772` | 10 / 132 | retain; semantic disposition pending |
| `codex/finalize-canonical-20261018` | `54db6bdbf2091a3bf7a66cf1124aa0c1a364931e` | 2 / 113 | retain; semantic disposition pending |
| `codex/issue-46-architecture` | `4cfd7a26945617fbe2c14fcadcf335e3d6def48e` | 4 / 161 | retain; semantic disposition pending |
| `codex/issue-6-release-evidence` | `7469e4a080e4a4b0a98825d91c3d695594317e16` | 7 / 132 | retain; semantic disposition pending |
| `governance/issue-54-forge-contract` | `398c3ac524e20d9d986cfb7df4c07cd54f1073be` | 4 / 1 | retain; semantic disposition pending |
| `proposal/korpus-capability-gateway-v1-20260904` | `f90a409bb8e2ab13aa90a15ed979885e2f43b413` | 152 / 265 | retain; semantic disposition pending |
| `work/issue-54-hosted-bootstrap` | `aa8fb96463f967ad7e7e4b0a83633f283c9511b1` | 43 / 113 | retain; semantic disposition pending |

The complete machine-readable snapshot is CANONICAL_BRANCH_INVENTORY.json beside this document.
Containment and patch identity are not semantic approval, deletion authority or production evidence.
No branch, tag, issue or existing PR is silently deleted/closed by this candidate.

## Operator validation

Use the repository's locked development environment and original CI commands.
From the repository root, `python scripts/kb_reference_admission.py` validates only the
18 reference metadata records. Its indexable/acquired counts remain zero and production
remains unauthorized. Package tooling retains the no-history and evidence-boundary policies;
do not interpret a self-consistent package hash as publisher authenticity or deployment approval.

Before main admission, re-read the candidate HEAD, main base, actual merge-candidate execution
receipts, all required CI jobs, and independent code AND security findings. Require real
server-side main protection and a genuine negative-control refusal record under #72.
No direct main write, force-push, permission bypass or automatic repinning is permitted.
A future rollback is a reviewed tested revert PR, not history rewriting or removal of gates.
