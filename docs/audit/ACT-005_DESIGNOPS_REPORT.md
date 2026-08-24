# ACT-005 — Design-System & UX Convergence Report

Target candidate: `v6.6.0`
Base HEAD: `8bfa16c6971987fc864f002ec208b232ab456b7f`

## Implemented

- DTCG-compatible canonical design tokens in `apps/web/design/tokens.json`.
- Deterministic generated `public/tokens.css`; direct token drift is rejected.
- Component/state registry for nine critical UI component families.
- Viewport contract for 390×844, 834×1112 and 1440×1000 proof surfaces.
- Shared tokens now serve consumer and operator interfaces.
- Consumer stylesheet can no longer introduce a competing `:root` palette.
- Mobile conversation disclosure no longer ships forced open; desktop opens it at boot.
- Mobile new-conversation action has an explicit accessible name.
- Conversation navigation uses contained scrolling and compact mobile height.
- High-value layout dimensions consume canonical tokens.
- Design-system scripts participate in syntax/lint/typecheck gates.
- Mutation controls prove generated-token drift and mobile disclosure regression are caught.

## Current verification

- Web tests: 121/121 PASS.
- Web lint: PASS.
- Web typecheck gate: PASS.
- Web build: PASS.
- Consumer transfer: 28,683 gzip bytes, below 32 KiB gate.
- Design system: 39 CSS tokens / 9 component contracts PASS.
- Contrast: 3 surfaces PASS under existing WCAG AA body-text gate.
- Static accessibility: 2 pages PASS.
- Internal import cycles: 0.
- Module budget: 177 modules / 0 violations.
- Release identity: v6.6.0 parity PASS without requiring a git tag.
- Backend architecture/release targeted run: all selected tests pass except the existing handoff-assurance binding test, which correctly refuses a source tree newer than the promoted assurance snapshot.

## Evidence limitation

The current execution environment blocks Chromium navigation with `ERR_BLOCKED_BY_ADMINISTRATOR`, so ACT-005 does not claim pixel-level visual regression PASS. The design source remains executable tokens/components/viewports; rendered browser baselines are the next evidence layer when a browser-capable environment is available.

## Promotion

`production_authorized=false` remains unchanged. No v6.6.0 git tag is created. Exact-lock backend assurance, live IdP/payment dependencies and production operational gates remain external blockers.
