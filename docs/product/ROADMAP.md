# Delivery roadmap — convergence sequence

## Gate 1 — structural convergence

One release identity, source/distribution manifests, acyclic internal imports, current
architecture/product SSOT, bounded backend/frontend modules. No product behavior change.

## Gate 2 — consumer SaaS completion

**Implemented in v6.4.0 candidate:** LiqPay client-server checkout boundary, signed callback
adapter, server-owned plan pricing, deployment plan bootstrap, subscription/account state and
consumer entitlement UX. Remaining before this gate closes: production merchant credentials,
live provider callback drill, explicit cancellation/renewal-management UX and self-service
sign-up configuration at the selected OIDC provider. Paid/inactive/tampered/replayed states
already have local negative controls.

## Gate 3 — premium responsive interface

**Implemented in v6.4.0 candidate:** custom tokenized consumer shell, responsive desktop/tablet/
mobile layouts, evidence-first conversation surface, history, account/subscription/pricing UI,
operator separation, accessibility and structural visual gates. Remaining: browser-level visual
regression baselines and device acceptance against the production edge.


**Implemented in v6.5.0 candidate:** premium consumer landing/workspace convergence,
plain-Enter chat interaction with Shift+Enter newline/IME protection, bounded auto-growing
composer, direct subscription-gate routing, accessibility busy/focus semantics and a
32 KiB first-party consumer gzip ratchet. Official promotion remains blocked on fresh
exact-lock assurance and live production dependencies.

**Implemented in v6.6.0 candidate:** repository-native DesignOps: DTCG-compatible design
tokens generate the browser palette, component/state and viewport contracts are executable,
mobile conversation history starts collapsed, focus/contrast/target semantics remain gated,
and design drift now has mutation controls. Browser-level pixel baselines remain external
because the current execution environment blocks Chromium navigation.

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


## v6.7.0 candidate — inference surface

**Implemented:** provider-neutral model contract, OpenAI Responses API adapter, Anthropic
adapter convergence on the same parsers/instructions, authenticated inference-status API,
server-side secret-file configuration, corpus-free inference smoke test and UI visibility of
model assistance. Model output remains non-authoritative and downstream evidence admission
remains deterministic. Live external transport is not claimed without a deployment key.
