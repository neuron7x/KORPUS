# KORPUS canonical distribution evidence boundary

## Trust boundary — issues #18 and #20

A self-consistent distribution manifest and a sealed runtime registry do **not** establish historical runtime-object authenticity. `var/evidence` and `var/releases` are retained operational objects, excluded from the canonical source ZIP and **not deleted** from their operational storage. The copied `reports/` tree can contain unverified records; package-level inventory integrity does not authenticate every report.

Canonical tracked `handoff/evidence/` and `reports/release/**/evidence/` remain admissible under distinct source/report contracts; arbitrary `reports/**/evidence` paths outside the release-report subtree are rejected, but pathname admission alone does not authenticate bytes. Runtime `var/evidence` and `var/releases` remain forbidden even inside wrapper directories. Windows trailing-dot/space path aliases are normalized before matching reserved components, with archive-wide normalized collision rejection. Trust is evaluated only from path components before the first `evidence` segment, so an outer `evidence/` cannot be laundered by a nested trusted prefix. The package producer refuses a staged top-level `evidence` directory; the ZIP verifier independently refuses top-level and singly wrapped `evidence/` entries **before extraction**, even after an adversary recomputes a fully consistent distribution manifest. The user-controlled registry contents cannot authorize themselves through hashes.

Source-manifest inventory no longer silently exempts `.bundle` paths. `git archive` alone can include a tracked history bundle: the producer now rejects staged `.bundle` files, and the consumer refuses ZIP bundle members before extraction. No claim that historical source contained actual credentials is made.

## Falsification / gates

`apps/api/tests/test_distribution_runtime_boundary.py` runs positive and poisoned self-consistent ZIP fixtures in flat and single-root layouts, asserts package producer exclusions, and verifies `.bundle` source eligibility. Record hosted exact-head API, PostgreSQL, research assurance, coverage and mutation results before merge. Do not weaken existing checks.

Production signing #8 remains a separate unsolved byte-identity/signature contract, and effective `main` protection issue #72 is mandatory. `production_authorized=false`; no deployment.

## Normalized-empty pathname components

Reject any path component that becomes empty after trailing-dot/space normalization. Apply this refusal before extraction even when an otherwise allowed reports or handoff prefix is present. Ordinary nonempty reports and handoff paths retain their existing contract. This is a parser guard, not production authorization.
