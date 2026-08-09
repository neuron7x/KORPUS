# KORPUS Chat Design Loop

This is the operating loop for design work performed in this chat without an external design-file dependency.

1. **OBSERVE** — inspect current HTML/CSS/JS, component contract and supplied screenshot/issue.
2. **DEFINE INVARIANT** — state what must remain true: trust semantics, accessibility, security, responsive behavior.
3. **MINIMAL DELTA** — change tokens/components/layout/interaction rather than painting over symptoms.
4. **IMPLEMENT** — edit the real product, not a detached mockup.
5. **FALSIFY** — add or update a negative control that fails when the intended design property is removed.
6. **VERIFY** — tests → lint/typecheck → build → structural/accessibility/size gates.
7. **VISUAL PROOF** — when browser execution is available, capture 390×844, 834×1112 and 1440×1000 and compare against acceptance criteria.
8. **PACKAGE** — manifest, Git bundle, checksum, candidate status.
9. **REPEAT** — next highest-impact UX debt only after the previous delta is green.

## Priority order

P0: task completion / evidence comprehension / auth & payment clarity.
P1: mobile navigation / composer / answer hierarchy / error recovery.
P2: typography rhythm / spacing / component consistency / microinteraction.
P3: decorative polish.

No P3 work may hide an unresolved P0/P1 defect.
