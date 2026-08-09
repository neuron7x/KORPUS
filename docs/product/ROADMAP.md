# Delivery roadmap — convergence sequence

## Gate 1 — structural convergence

One release identity, source/distribution manifests, acyclic internal imports, current
architecture/product SSOT, bounded backend/frontend modules. No product behavior change.

## Gate 2 — consumer SaaS completion

Production payment provider, checkout/webhook lifecycle, subscription/account controls,
consumer onboarding and entitlement UX. Exit: paid/inactive/canceled/replayed states pass
negative controls end to end.

## Gate 3 — premium responsive interface

Custom design system, mobile-first conversation experience, evidence disclosure, history,
account/subscription surfaces, operator separation, accessibility and visual regression.
Exit: phone and desktop acceptance matrices pass with no trust-state ambiguity.

## Gate 4 — production corpus and operations

Materialize approved corpus, rights/provenance decisions, backup/restore, monitoring,
capacity/cost measurements, external TLS/KMS/service configuration and recovery drills.

## Gate 5 — controlled production authorization

Independent security assessment, risk-owner decision, production SLO evidence, incident
workflow and release evidence bound to the deployed artifact. `production_authorized`
remains false until this gate is explicitly signed.

## Future capability track

Instructor tools, administrative drafts, voice/photo input and native apps remain backlog
hypotheses and do not participate in current MVP readiness.
