# KORPUS Design System — Code-First SSOT

## Purpose

KORPUS does not require a `.fig` file as the authoritative design source. The executable design contract lives with the product and is reviewed, versioned and tested like code.

## Sources of truth

- `apps/web/design/tokens.json` — canonical DTCG-compatible tokens.
- `apps/web/public/tokens.css` — generated browser representation; manual edits are rejected.
- `apps/web/design/components.json` — component anatomy, variants, states and invariant contracts.
- `apps/web/design/viewports.json` — breakpoint and interaction contracts.
- `apps/web/scripts/design_system.mjs` — deterministic parity validator.

## Non-negotiable product semantics

1. Evidence is part of an answer, not a decorative footnote.
2. Declared user context is never styled as verified authorization.
3. Conversation history is context and never becomes evidence.
4. Payment refusal is visually and semantically distinct from evidence refusal.
5. No critical action depends on hover, drag or pointer precision.
6. Compact screens protect the query task from navigation panels by default.

## Viewport proof set

- 390 × 844 — compact mobile.
- 834 × 1112 — tablet.
- 1440 × 1000 — desktop.

Browser screenshot automation is an evidence layer, not the design source. Where the execution environment blocks Chromium navigation, the candidate remains without pixel-regression promotion evidence rather than fabricating screenshots.
