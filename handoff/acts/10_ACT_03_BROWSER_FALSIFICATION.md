# ACT-03 — Browser-boundary falsification

- Issue ID: `KORPUS-ACT-03`.
- Value hypothesis: real-browser adversarial tests detect security, accessibility, concurrency, responsive-layout, and state-management defects that static marker checks cannot observe.
- Trust boundary: untrusted API payload ↔ DOM; cookie/session state ↔ browser memory; keyboard/assistive technology ↔ controls; asynchronous transport ↔ visible result state; CI image ↔ reproducible browser.
- Allowed files: `apps/web/`, `.gitlab-ci.yml`, this act, transient `var/web-act/` evidence.
- Forbidden files: backend authorization, production data, audit source, fake application logic, runtime analytics, production authorization.
- Killable invariants: all API strings are inert text; CSRF is copied only from the dedicated cookie; bearer authority is not persisted; missing identity is explicit; stalled transport fails closed within 15 seconds; keyboard submission works; 390-pixel layout has no horizontal overflow; automated WCAG A/AA serious or critical violations are zero.
- Test partitions: authenticated/unauthenticated; success/stall; benign/XSS-bearing payload; pointer/keyboard; desktop/mobile; static/runtime accessibility.
- Tool decision: Playwright supplies deterministic browser orchestration and trace/JUnit evidence; axe-core supplies a bounded automated accessibility oracle. Neither substitutes for manual assistive-technology testing or independent review.
- Acceptance predicates: five browser cases pass against the production build; web static gates pass; exact dependency versions are locked; CI uses a matching Playwright image and retains JUnit/failure traces; repository gates remain green.
- Rollback: revert the single ACT-03 commit. No migration or persistent data impact.
- Uncertainty: automated accessibility cannot establish complete WCAG conformance; route interception tests the browser contract, not a live OIDC provider or production network.
