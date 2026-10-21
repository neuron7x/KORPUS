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

## Branch disposition (2026-10-21 continuation)

The original CANONICAL_BRANCH_INVENTORY.json remains an immutable dated observation.
The companion CANONICAL_BRANCH_DISPOSITION.json records subsequent source-level decisions,
exact legacy pins, current-test matches and retained implementation dependencies.
Twenty-five tips were already ancestors of the main baseline. The package stack is represented
once; do not merge both its component PRs and the aggregate as independent source imports.

Read-only static audit run 39629417088 examined all five residual tips against source
c2abdb69edd273c53e3a7bb2344f1ffb3be2a158. Artifact 12357074758 was independently hash-checked:
363e3d95c1ad36dfa8020655acfef0e7f463cb8d62b01df8a14a0e5d8c57b305.
All 730 internal evidence-file hashes were verified. No legacy code was executed.

| Legacy tip | Disposition | Rationale |
| --- | --- | --- |
| agent/ci-local-ref-isolation-20261018 | SUPERSEDED | Four changed definitions retained; three named tests pass in original candidate CI. |
| codex/issue-46-architecture | SUPERSEDED | Current composition, gateway and deadline implementation covers the changes; 50 matched cases pass. The old local verification log remains historical. |
| codex/issue-6-release-evidence | ADAPTED_PENDING_FULL_CI | Restore isolated receipt staging only; preserve newer dependencies and controls; never promote its 86 generated paths as fresh evidence. |
| proposal/korpus-capability-gateway-v1-20260904 | SUPERSEDED | Current hardened implementation retains all 247 named test functions (277 matched cases pass). Do not reintroduce the unused registry.versions helper as a public API. |
| work/issue-54-hosted-bootstrap | RETAIN_EXCLUDED_PENDING_SCOPED_ADAPTATION | 33 absent paths belong in a scoped current-architecture assessment under #66/#67, not a blind workflow rollback. Those obligations remain OPEN. |

The auxiliary governance/issue-54-forge-contract and audit/pr85-empty-component-fix-20261021
tips have no additional net source import (review 5601034069). codex/finalize-canonical-20261018
is semantically superseded by current all-parent traversal and its killed M727 control
(review 5602153926). Source disposition is not ancestry equivalence: all refs and original
commits remain intact; no branch, tag, issue or component PR is deleted or silently closed.
Five of five residual tips are classified; not all historic implementation debt is closed.

## Regression-receipt staging correction

The previous backend-report target overwrote tracked shard receipts while later workers still
inspected the checkout. A failed worker could leave a mixture of old and new evidence.
Each invocation now creates a unique staging directory under var, directs every worker there,
preserves prior tracked receipts during worker execution, and stops before promotion if a worker
fails. Positive shard count is required. Normal exit and handled signals clean the temporary path.
Only a fully successful worker loop replaces the canonical shard directory; the original exact
shard-merge verifier and backend publisher then run unchanged. Direct regression-shard commands
retain their original output default and may explicitly set REGRESSION_SHARD_DIR.

Sixteen isolated tests execute the actual Make recipes with inert Python producers: normal and
space-containing workspaces, two/three workers, failure of first/later workers, explicit staging
paths, and invalid counts. Named guard regressions test early live writes, ignored worker failures
premature deletion, and omitted cleanup. Tests do not activate services, acquire content or invoke production tools.
The existing no-deletion-before-self-tests contract is retained and made order-sensitive: deletion
is forbidden before/during the worker loop, while verified post-worker promotion remains allowed.
Its test name and all other shard-contract checks are preserved.
This is worker-phase isolation, NOT crash-atomic directory promotion or concurrent-worktree support.
A promotion/merge/publisher failure still blocks completion; the one-worktree-per-agent contract applies.

The complete generated source identity is rebound after this change. Full hosted CI and independent
CODE/SECURITY assessment must cover the final commit; earlier c2abdb69 results are historical.

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
