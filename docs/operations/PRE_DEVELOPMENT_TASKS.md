# Pre-development task map

This map separates prerequisites for disciplined repository development from
production-authorization work. It is ordered by dependency and value, not by feature
novelty.

## P0 — development-control plane

1. **Truthful GitHub governance bootstrap — IMPLEMENTED by issue #1 / PR #2; enforcement blockers remain below.**
   Real CODEOWNER, complete issue contract, isolated worktree, readiness observation,
   vulnerability alerts and draft-PR path.
2. **Restore executed GitHub evidence — BLOCKED_EXTERNAL.**
   Resolve the account billing lock, rerun `ci`, `assurance`, and dependency review,
   then record exact check names. Source workflow files are not execution evidence.
3. **Make `main` enforceably protected — BLOCKED_EXTERNAL.**
   GitHub returned HTTP 403 for branch protection on this private repository under the
   current plan. Upgrade or an explicit visibility decision is required. Until then,
   direct pushes remain technically possible and merges require owner discipline.

## P1 — establish the executable baseline

4. Rebuild the locked Python and web environments from the canonical locks.
5. Run repository, API, quality, web, evaluation, migration, and operational gates
   locally; bind results to the current `main` commit rather than inherited candidate
   evidence from another release line.
6. Reconcile release identity: `v0.1.1` is the collaboration baseline while bundled
   candidate evidence names `v6.7.0` and reports stale release binding. Produce fresh
   evidence or keep the candidate evidence explicitly historical.
7. Run the PostgreSQL/pgvector suite and container/runtime checks on a capable host;
   SQLite-only success does not close dialect or infrastructure risk.

## P2 — choose product work through the value function

8. Select one open/synthetic corpus and one user journey. Do not import restricted or
   rights-uncleared data.
9. Freeze an evaluation set that measures supported evidence delivery, access leakage,
   stale authority, citation integrity, abstention, latency and human review cost.
10. Choose the next feature only if it improves that value function without violating
    the zero-tolerance invariants in `docs/assurance/FIRST_PRINCIPLES.md`.

## Production track — not a coding prerequisite and not locally closable

The nine external debts in `docs/operations/CURRENT_STATUS.md` require owners, rights
decisions, real infrastructure, human labels, independent TEVV/security work, on-call
operations or repository controls. Development may build evidence for them but may not
mark them closed.

## First valid feature issue

After P0–P1, create a separate issue for a single open-data user journey and define:
value hypothesis, trust boundary, killable invariants, negative controls, acceptance
predicates, forbidden changes, rollback/migration and independent verifier evidence.
Do not begin broad feature implementation from this governance issue.
