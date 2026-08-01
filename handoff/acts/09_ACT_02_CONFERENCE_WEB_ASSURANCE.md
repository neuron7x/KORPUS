# ACT-02 — Conference web assurance

- Issue ID: `KORPUS-ACT-02`.
- Value hypothesis: a compact, evidence-native interface can make KORPUS's trust boundary legible without adding framework, dependency, authority, or performance debt.
- Trust boundary: browser ↔ BFF/API; human interpretation ↔ machine evidence; conference claim ↔ reproducible measurement.
- Allowed files: `apps/web/`, this act, bounded CI/web validation wiring, transient `var/web-act/` evidence.
- Forbidden files: audit source, production authorization, backend policy, real corpus data, fake API responses, fabricated benchmarks, external tracking or font/CDN dependencies.
- Killable invariants: inaccessible data never renders; untrusted values are escaped; browser token stays memory-only; session cookie is never read by JavaScript; mutating requests preserve CSRF; timeout/cancellation are explicit; keyboard and focus flow remain operable; layout reflows at 390 CSS pixels; reduced-motion and increased-contrast preferences are honored; shell assets remain below 40 kB uncompressed; no external runtime dependency is introduced.
- Adversarial cases: absent identity, failed API, delayed API, repeated submission, HTML-bearing source values, narrow viewport, keyboard-only use, reduced motion, high contrast, offline shell, and claims that exceed encoded evidence.
- Acceptance predicates: web lint/typecheck/build pass; deterministic validator passes; desktop/mobile Chromium renders are inspected; no horizontal mobile clipping; relevant repository gates pass; every unmeasured claim remains qualified; `production_authorized=false` remains visible and true.
- Rollback: revert the single ACT-02 commit; no migration or persistent data transformation.
- Standards baseline: W3C WCAG 2.2; WHATWG semantic HTML; Core Web Vitals (LCP, CLS, INP); OWASP ASVS; KORPUS threat model and assurance case. Standards guide killable predicates but do not create an unsupported conformance claim.
- Evidence: transient screenshots and command logs under `var/web-act/`; no secrets or user data.
- Independent verification: required before any claim of WCAG conformance, production fitness, or comparative superiority.

## Claim discipline

The conference claim is not “best in the world.” The defensible claim is: KORPUS demonstrates a dependency-free evidence interface whose authorization, provenance, limitation, performance-budget, and accessibility properties are explicit and executable. Comparative superiority requires a frozen benchmark, named alternatives, equivalent environments, raw results, and an independent evaluator.
