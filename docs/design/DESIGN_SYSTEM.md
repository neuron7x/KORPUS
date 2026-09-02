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
- 768 × 1024 — tablet.
- 1440 × 1000 — desktop.

Browser screenshot automation is an evidence layer, not the design source. Where the execution environment blocks Chromium navigation, the candidate remains without pixel-regression promotion evidence rather than fabricating screenshots.


> **ВИПРАВЛЕНО 02.09.2026.** Ширина планшета значилась як `834 × 1112`. SSOT, названий
> цими ж документами — `apps/web/design/viewports.json` — дає `proofViewports`
> 320×700 / 390×844 / **768×1024** / 1440×1000. Ширини 834 в коді немає взагалі.
> Окремо: `proofViewports` не читає ЖОДЕН виконуваний файл, тож і SSOT тут поки що
> оголошення, а не гейт.
