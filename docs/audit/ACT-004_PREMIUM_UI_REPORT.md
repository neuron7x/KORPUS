# ACT-004 — Premium Consumer UI / Interaction Report

Target candidate: `v6.5.0`
Date: 2026-08-09

## Scope

ACT-004 changes only the consumer web surface and release identity. It does not change
retrieval, evidence admission, authorization, subscription adjudication, database
semantics, LiqPay signature verification, or answer composition semantics.

## Implemented

### Consumer landing

- Replaced the technical-first landing copy with a consumer-first evidence proposition.
- Preserved explicit fail-closed semantics: no evidence means no factual answer.
- Added an evidence trace preview that exposes retrieve → verify → answer without claiming
  a calibrated probability of truth.
- Preserved OIDC login and the separate short-lived service-token path.

### Authenticated workspace

- Rebuilt the desktop shell into a bounded three-surface layout: navigation/history,
  evidence chat, evidence guide.
- Added tablet convergence to two surfaces and a mobile single-column shell.
- Kept conversation history explicitly labelled as context rather than evidence.
- Kept declared session context visually and semantically distinct from verified identity.
- Reworked live answer hierarchy: user question, verdict, answer, metrics, citations,
  limitations.

### Composer interaction

- Plain Enter submits.
- Shift+Enter creates a newline.
- IME composition cannot submit accidentally.
- The textarea auto-sizes up to a bounded 190 px height.
- Busy state is exposed through `aria-busy` on the composer and result region.
- Network failure still preserves the unsent question.

### Subscription gate

- A commercially locked account is taken directly to the pricing surface.
- The pricing region receives keyboard focus after the state transition.
- Pricing continues to consume server-owned prices and server-created checkout descriptors.
- No card number, CVV, or merchant secret is handled by the browser application.

### Design-system constraints

- One palette SSOT remains enforced.
- No external font, icon, UI framework, CSS framework, or client dependency was added.
- WCAG static structure and token contrast gates remain executable.
- Consumer first-party text transfer now has a deterministic gzip ratchet:
  - total consumer entry budget: `<= 32 KiB gzip`;
  - consumer stylesheet budget: `<= 8 KiB gzip`.

## Executable evidence

### Web

- `119/119` Node tests PASS.
- Web syntax/lint gate PASS.
- Static accessibility gate PASS for both shipped pages.
- Contrast gate PASS across three surface tokens.
- Typecheck gate PASS.
- Production static build PASS.
- Current measured consumer entry transfer: `28195 gzip bytes`.

### Backend regression groups

No backend behavior was intentionally changed in ACT-004. Post-change regression groups:

- structural/release/manifest/web-score: `30/30 PASS`;
- tenancy/billing/LiqPay: `71/71 PASS`;
- auth/answers/conversations: `48/48 PASS`.

Total completed targeted backend evidence: `149/149 PASS`.

### Structural gates

- Internal import cycles: `0`.
- Module budget: `177 modules`, `0 violations`.
- Repository requirements: `103/103 PASS`.
- Release identity parity without git tag: PASS for API package, web package, web lock,
  desired state and README.

## Negative controls added/updated

- A mutation that changes plain Enter into newline-only behavior must fail validation.
- A mutation that makes verified and declared identity styling equivalent must fail.
- A mutation that drops body-text contrast below WCAG AA must fail.
- A mutation that bloats the first-party consumer payload above the gzip budget must fail.

The two existing CSS mutation controls were updated because ACT-004 changed the exact
palette/selector literals; their protected predicates were not weakened.

## External blocker — exact assurance

A clean virtual environment attempted installation from the repository's hashed runtime
lock. The available package mirror returned no distribution for `alembic==1.18.4`.
Therefore the exact locked Python environment cannot be reproduced in this execution
container. Fresh full-suite/coverage/mutation/reference-eval assurance is not claimed.

The release remains a candidate. No `v6.5.0` git tag is created and
`production_authorized` remains false until the authoritative environment and the
remaining external production gates are satisfied.

## Verdict

ACT-004 implementation: `PASS_WITH_CAVEATS`.

Consumer web behavior and structural gates: `PASS`.
Official release promotion: `FAIL / NOT_READY_FOR_PROMOTION` because fresh exact-lock
assurance is unavailable in this environment and live production dependencies remain
external.
