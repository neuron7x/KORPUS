# ACT-003 — SaaS Surface Implementation Report

Status date: 2026-08-09
Target candidate: `v6.4.0`
Base commit: `59884cc3d3ed1f9ff060fae4ce8e788b03e00fa1`
Promotion status: `PASS_WITH_CAVEATS / NOT_READY_FOR_PROMOTION`
Production authorization: `false`

## Mission

Extend the structurally defragmented KORPUS candidate with a production-oriented consumer SaaS surface while preserving the existing evidence-bound answer kernel and fail-closed authorization semantics.

The implemented path is:

`identity -> account -> server-owned plan -> checkout -> verified billing event -> subscription -> entitlement -> conversation -> evidence retrieval -> supported answer or abstention`

No browser field is authoritative for account identity, price, currency, subscription status, corpus entitlement, or evidence authority.

## Implemented workstreams

### 1. Sellable plan domain

Implemented server-owned commercial plan fields:

- integer `price_minor`;
- `currency`;
- atomic price/currency validation;
- database constraints;
- forward migration `0015_plan_pricing`;
- schema revision `0015_plan_pricing`.

A deployment-owned plan bootstrap materializes or synchronizes the configured sellable plan idempotently. Commercial values originate from server configuration, not from the browser.

### 2. Provider-neutral checkout boundary

Added `CheckoutProvider`, `CheckoutService`, and `CheckoutDescriptor` boundaries.

The checkout service resolves the authenticated account and plan server-side, creates the subscription in `INCOMPLETE`, and returns only an allow-listed external checkout descriptor.

### 3. LiqPay adapter

Added an isolated LiqPay adapter with:

- signed checkout payload creation;
- explicit signature algorithm policy;
- exact merchant-key verification;
- bounded callback body parsing;
- deterministic event identity;
- duplicate-event idempotency;
- terminal/intermediate status separation;
- server-side amount and currency reconciliation;
- bounded active subscription period derivation;
- no collection or storage of card data inside KORPUS.

### 4. Billing adjudication decomposition

Billing event verification and event adjudication are separated.

The adjudicator owns:

- subscription resolution;
- event ordering;
- price/currency reconciliation;
- lifecycle transition validation;
- period bounds;
- applied/rejected event persistence.

This reduced orchestration concentration without raising module-budget ceilings.

### 5. Consumer SaaS web surface

Rebuilt the consumer surface around the executable product flow:

- unauthenticated product landing;
- authenticated account state;
- subscription state;
- pricing surface;
- external checkout handoff;
- conversation list;
- evidence-first chat;
- citation/evidence visibility;
- explicit unsupported-answer state;
- responsive desktop/tablet/mobile layout;
- keyboard submission;
- reduced-motion handling;
- accessibility labels/focus targets;
- explicit separation between declared session context and verified identity/evidence.

The browser transport boundary remains centralized in `api.js`.

### 6. CSP/payment-origin control

The production nginx CSP permits form submission only to self and the exact LiqPay checkout origin. A negative-control validator test fails if the payment origin is removed.

### 7. Structural ratchet preservation

No module-budget ceiling was increased to absorb ACT-003.

After decomposition:

- `routes_billing.py`: 165 LOC;
- `routes_tenancy.py`: 403 LOC;
- `subscriptions.py`: 143 LOC;
- `tenancy_composition.py`: 55 LOC;
- internal import cycles: 0.

The module-budget checker reports 177 modules, zero unbudgeted modules, zero violations.

## Executed verification after final structural refactor

### Backend targeted regression evidence

Completed, assertion-clean runs:

- billing / tenancy API / billing events / migration / schema pin: `60/60 PASS`;
- controlled configuration / entitlement gate: `53/53 PASS`;
- conversations / tenancy threats: `30/30 PASS`;
- model egress: `14/14 PASS`.

Total completed targeted backend tests: `157/157 PASS`.

These tests cover the changed commercial, entitlement, ownership and egress boundaries. They are not represented as a substitute for the full authoritative backend suite.

### Web evidence

Final ACT-003 web run:

- tests: `117/117 PASS`;
- syntax validation: `17 modules PASS`;
- lint gate: `PASS`;
- typecheck gate: `PASS`;
- production build: `PASS`;
- contrast validation: `3 surfaces PASS`;
- structural accessibility validation: `2 pages PASS`.

### Structural evidence

- `git diff --check`: PASS;
- Python source `compileall`: PASS;
- internal import-cycle checker: PASS, zero cycles;
- module-budget checker: PASS, 177 modules, zero violations;
- release-identity parity before tag: PASS;
- repository validator: PASS before final manifest refresh.

## OpenAPI result

ACT-003 intentionally adds:

- `/v1/billing/checkout`;
- `CheckoutView`;
- the commercial fields in `PlanView`.

The stored OpenAPI contract was updated only for these intentional deltas.

The local system environment has FastAPI/Starlette versions different from the repository lock. Four pre-existing multipart-body schemas therefore render differently locally. The entire contract was not regenerated from that non-authoritative environment.

## Verification limitations

The following are explicitly NOT claimed as PASS for this candidate:

1. exact repository-locked Python environment reproduction;
2. complete authoritative backend suite on the final ACT-003 HEAD;
3. fresh full coverage report bound to the final ACT-003 HEAD;
4. fresh mutation report bound to the final ACT-003 HEAD;
5. fresh reference evaluation bound to the final ACT-003 HEAD;
6. fresh assurance snapshot bound to the final ACT-003 HEAD;
7. production merchant callback verification against live LiqPay credentials;
8. production IdP self-registration acceptance;
9. browser/device visual-regression baseline on production rendering infrastructure;
10. production authorization.

The package mirror available in the execution environment cannot reproduce the exact pinned Python dependency set. This condition is treated fail-closed rather than silently substituting a different framework stack.

## Production blockers remaining

- provision production LiqPay merchant credentials and verify live callback behavior;
- configure/test identity-provider self-registration and recovery lifecycle;
- define user-facing cancellation/refund management behavior;
- reproduce exact Python lock and run the full authoritative verification suite;
- regenerate source-bound coverage, mutation, reference-eval and assurance evidence;
- execute browser/device visual regression and production-edge acceptance;
- resolve the repository's external admission/production debts;
- set `production_authorized=true` only through the existing governance mechanism after all mandatory gates pass.

## Result

ACT-003 functional candidate: `PASS_WITH_CAVEATS`.

Structural gates: `PASS`.

Consumer SaaS surface: `IMPLEMENTED / TESTED AT LOCAL CONTRACT LEVEL`.

Payment provider boundary: `IMPLEMENTED / LIVE PRODUCTION VERIFICATION PENDING`.

Production promotion: `FAIL / NOT_READY_FOR_PROMOTION`.
