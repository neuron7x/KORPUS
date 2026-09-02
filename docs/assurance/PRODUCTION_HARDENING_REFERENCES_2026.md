# KORPUS production-hardening reference basis — 2026-08-16

This is a scoped control-mapping note. The complete canonical bibliography is
`config/assurance/ASSURANCE_SOURCE_REGISTRY_2026.json`, rendered at
`docs/research/BIBLIOGRAPHY_2026.md`.

This document records the external engineering and evaluation basis mapped by `config/assurance/standards-control-map.v1.json`. A reference motivates a requirement; it is **not** evidence that KORPUS satisfies that requirement. Local satisfaction requires executable, source-bound evidence. Requirements that inherently need a production-like environment, current external database, trusted builder, or independent evaluator remain external and fail closed when absent.

## Normative / final references

- **NIST SP 800-218, SSDF 1.1** — secure software development practices. KORPUS maps it to immutable dependency closure, source/release provenance, static security floors, release evidence, and fail-closed promotion. https://doi.org/10.6028/NIST.SP.800-218
- **NIST SP 800-218A** — final SSDF community profile for Generative AI and Dual-Use Foundation Models. It informs AI-specific threat/evidence treatment without claiming KORPUS is itself a foundation model. https://doi.org/10.6028/NIST.SP.800-218A
- **NIST AI 600-1, Generative Artificial Intelligence Profile** — final cross-sector companion to AI RMF 1.0 for identifying and managing GenAI-specific risks through the AI lifecycle. KORPUS uses it as risk/evaluation methodology, not as certification. https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence
- **OWASP ASVS 5.0.0** — application security verification requirements. KORPUS uses it as an application-control reference for authorization, input/security boundaries, secrets and dangerous primitives. https://owasp.org/www-project-application-security-verification-standard/
- **SLSA v1.2** — software supply-chain specification. KORPUS emits structurally verifiable in-toto/SLSA-compatible provenance, but a local unattested builder explicitly claims **no SLSA level**. https://slsa.dev/spec/v1.2/

## Draft / informative reference

- **NIST SP 800-218 Rev.1 / SSDF 1.2 Initial Public Draft** — released 2025-12-17 and still listed by NIST as a draft in 2026. It is tracked as `draft-informative`, never silently promoted to final normative authority. https://csrc.nist.gov/pubs/sp/800/218/r1/ipd

## 2026 frontier-evaluation methodology

- **OpenAI, “A shared playbook for trustworthy third party evaluations” (2026)** — separates evaluation claims into capability elicitation, safeguard performance, and comparison; requires the tested system/harness, budget, elicitation method, and validity hazards to be visible. It explicitly names reward hacking, refusals, contamination, broken problems, and sandbagging as validity risks. KORPUS therefore binds an explicit harness contract into its local evaluation report and refuses to treat a self-evaluation as independent production evidence. https://openai.com/index/trustworthy-third-party-evaluations-foundations/
- **OpenAI, “Separating signal from noise in coding evaluations” (2026)** — demonstrates that benchmark task defects can materially distort conclusions and argues for task-level quality auditing rather than trusting aggregate scores. KORPUS applies the principle by freezing and hashing its dataset/protocol/harness, retaining case-level outcomes, and separating fixture assurance from production TEVV. https://openai.com/index/separating-signal-from-noise-coding-evaluations/
- **OpenAI, “Inside our approach to the Model Spec” (2026)** — makes intended behavior explicit, hierarchical and evaluable, while distinguishing a behavioral specification from its implementation. KORPUS uses the analogous systems principle: policy/authority boundaries are explicit artifacts and machine-tested; retrieved text or model output cannot outrank application policy. https://openai.com/index/our-approach-to-the-model-spec/
- **Stanford CRFM HELM Capabilities** — publishes prompt-level transparency and reproducible evaluation through the HELM framework. KORPUS adopts the reproducibility principle by binding dataset, protocol, harness and system-manifest hashes to evaluation output. https://crfm.stanford.edu/helm/capabilities/latest/
- **Stanford HAI 2026 AI Index, Technical Performance** — reports rapid benchmark saturation and substantial reliability/gaming concerns in widely used evaluations. KORPUS therefore treats a score as evidence only for the exact frozen harness and refuses extrapolation from synthetic fixture performance to production capability. https://hai.stanford.edu/ai-index/2026-ai-index-report/technical-performance

## Research references

- **Lamb & Zacchiroli, Reproducible Builds: Increasing the Integrity of Software Supply Chains** (arXiv:2104.06020). Motivation for deterministic build/rebuild comparison; no external performance result is inherited. https://arxiv.org/abs/2104.06020
- **Rag and Roll** (arXiv:2408.05025). Evidence that indirect prompt manipulation is a concrete RAG threat surface. KORPUS treats retrieved content as data and destruction-tests that hostile retrieved text cannot become planner/composer authority. https://arxiv.org/abs/2408.05025
- **Overcoming the Retrieval Barrier** (arXiv:2601.07072). Contemporary research on indirect prompt injection in retrieval systems; it motivates adversarial-evaluation breadth, not a claim that KORPUS implements the paper's detector or measured success rates. https://arxiv.org/abs/2601.07072

## Evaluation doctrine

1. **Claim before score.** Every evaluation states whether it tests a capability ceiling, safeguard performance, or a comparison.
2. **Harness is part of the tested system.** Dataset, protocol, system manifest, model/tool configuration, execution budget and harness contract are content-bound where applicable.
3. **Validity hazards are explicit.** Reward hacking, refusals, contamination, broken tasks and sandbagging are either tested or explicitly classified as inapplicable with a reason; silence is not PASS.
4. **Fixture ≠ production TEVV.** A synthetic SQLite run can prove local invariants; it cannot establish real-corpus calibration, PostgreSQL behavior, production SLOs or external independence.
5. **A citation is not a PASS.** A control becomes `EXECUTABLE` only when the repository contains deterministic evidence and a negative/destruction control where practical.
6. **Offline structural checks ≠ live vulnerability scans.** Current vulnerability status remains external until OSV or an equivalent live scanner actually executes.
7. **Self red-team ≠ independent red-team.** Local adversarial campaigns improve the artifact but do not clear the independent-evidence predicate.
8. **Local provenance ≠ trusted builder.** Artifact/source binding may be proved locally; hosted-builder trust and deployment attestation cannot be self-issued.
9. **Production authorization is conjunctive.** UNKNOWN, missing, stale, wrong-source, wrong-release or weaker-class evidence fails closed.
