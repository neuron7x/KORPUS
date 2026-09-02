# ACT-005 — Design-System & UX Convergence

## Intent
Replace the external design-file dependency with an executable, repository-native design workflow while preserving KORPUS trust semantics.

## Scope
1. Canonical design tokens and deterministic CSS generation.
2. Component/state registry.
3. Responsive viewport contracts.
4. Accessibility and target/focus contracts.
5. Mobile information-architecture correction.
6. Visual hierarchy and interaction hardening.
7. Mutation tests proving design gates can fail.
8. Candidate packaging and handoff evidence.

## Iteration sequence
- I1 Foundation: tokens → components → viewports → validators.
- I2 Information architecture: landing → account → subscription → chat → evidence.
- I3 Component refinement: composer, verdict, citations, navigation, plan card, errors.
- I4 Responsive proof: 390/834/1440 plus keyboard and reduced-motion behavior.
- I5 Visual regression: browser screenshots when an execution environment permits Chromium navigation.
- I6 Release convergence: source manifest, package manifest, Git bundle, checksum.

## Promotion rule
No visual claim becomes PASS from prose alone. It needs a deterministic structural gate or rendered browser evidence.


> **ВИПРАВЛЕНО 02.09.2026.** Ширина планшета значилась як `834 × 1112`. SSOT, названий
> цими ж документами — `apps/web/design/viewports.json` — дає `proofViewports`
> 320×700 / 390×844 / **768×1024** / 1440×1000. Ширини 834 в коді немає взагалі.
> Окремо: `proofViewports` не читає ЖОДЕН виконуваний файл, тож і SSOT тут поки що
> оголошення, а не гейт.
