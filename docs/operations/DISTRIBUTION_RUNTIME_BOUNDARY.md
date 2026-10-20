# KORPUS canonical distribution evidence boundary

## Trust boundary — issues #18 and #20

A self-consistent distribution manifest and a sealed runtime registry do **not** establish historical runtime-object authenticity. `var/evidence` and `var/releases` are retained operational objects, excluded from the canonical source ZIP and **not deleted** from their operational storage. Current `reports/`, source and selected SBOMs remain under existing contracts.

Canonical tracked `handoff/evidence/` reports remain admissible; their consumer contract is distinct from runtime `var/evidence` and `var/releases`. The package producer refuses a staged top-level `evidence` directory; the ZIP verifier independently refuses top-level and singly wrapped `evidence/` entries **before extraction**, even after an adversary recomputes a fully consistent distribution manifest. The user-controlled registry contents cannot authorize themselves through hashes.

Source-manifest inventory no longer silently exempts `.bundle` paths. `git archive` excludes the history/refs/deleted objects rather than packaging a `git bundle`. No claim that historical source contained actual credentials is made.

## Falsification / gates

`apps/api/tests/test_distribution_runtime_boundary.py` runs positive and poisoned self-consistent ZIP fixtures in flat and single-root layouts, asserts package producer exclusions, and verifies `.bundle` source eligibility. Record hosted exact-head API, PostgreSQL, research assurance, coverage and mutation results before merge. Do not weaken existing checks.

Production signing #8 remains a separate unsolved byte-identity/signature contract, and effective `main` protection issue #72 is mandatory. `production_authorized=false`; no deployment.
