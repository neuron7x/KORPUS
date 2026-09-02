# KORPUS production-hardening reference basis — 2026-08-16

This is a scoped architecture note. The complete canonical bibliography is
`config/assurance/ASSURANCE_SOURCE_REGISTRY_2026.json`, rendered at
`docs/research/BIBLIOGRAPHY_2026.md`.

This file records the external engineering basis for controls implemented in this tree.
A citation here is not evidence that KORPUS satisfies a standard. Satisfaction is carried
only by executable local evidence and, where required, independently generated evidence.

## Normative and industry references

### NIST Secure Software Development Framework

- NIST SP 800-218, **SSDF Version 1.1**, final (2022):
  https://doi.org/10.6028/NIST.SP.800-218
- NIST SP 800-218A, **Secure Software Development Practices for Generative AI and
  Dual-Use Foundation Models**, final (2024):
  https://doi.org/10.6028/NIST.SP.800-218A
- NIST SP 800-218 Rev. 1 / SSDF Version 1.2 is an **Initial Public Draft** as of this
  release, not a final normative replacement for SSDF 1.1:
  https://csrc.nist.gov/Projects/ssdf/publications

KORPUS mapping: immutable dependency locks, source/release identity, threat-driven tests,
negative controls, vulnerability-scan evidence boundaries, reproducible package checks,
and AI-specific provenance/evaluation records. A local package does not claim complete
SSDF conformance; deployment/process controls remain external evidence.


### NIST AI risk and AI-specific secure development

- NIST AI 600-1, **Artificial Intelligence Risk Management Framework: Generative AI
  Profile**, final publication (2024; NIST page updated 2026-04-08):
  https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence
- NIST SP 800-218A, **Secure Software Development Practices for Generative AI and
  Dual-Use Foundation Models**, final (2024):
  https://csrc.nist.gov/pubs/sp/800/218/a/final

Engineering consequence: AI assurance is lifecycle risk management, not a benchmark score.
KORPUS separates evaluand identity, harness, source-bound evidence, safeguard claims and
production authorization. Unknown external predicates remain explicit unknown/fail states.

### Frontier evaluation validity — OpenAI 2026

- OpenAI, **A shared playbook for trustworthy third party evaluations** (2026):
  https://openai.com/index/trustworthy-third-party-evaluations-foundations/
- OpenAI, **Separating signal from noise in coding evaluations** (2026):
  https://openai.com/index/separating-signal-from-noise-coding-evaluations/
- OpenAI, **Inside our approach to the Model Spec** (2026):
  https://openai.com/index/our-approach-to-the-model-spec/

Engineering consequence: an evaluation result is interpreted only together with the claim,
tested system, harness, resource budget and validity checks. Reward hacking, refusals,
contamination, broken problems, evaluation awareness/sandbagging and harness drift are explicit
validity hazards. Local self-evaluation cannot substitute for independent third-party evidence.
`evals/EVALUATION_HARNESS_CONTRACT.json` makes this boundary machine-readable.

### Reproducible model evaluation — Stanford CRFM / Stanford HAI

- Stanford CRFM, **HELM Capabilities**:
  https://crfm.stanford.edu/helm/capabilities/latest/
- Stanford HAI, **2026 AI Index — Technical Performance**:
  https://hai.stanford.edu/ai-index/2026-ai-index-report/technical-performance

Engineering consequence: benchmark saturation, task defects and harness differences make a single
headline score an invalid proxy for a general cognitive ceiling. KORPUS therefore treats results as
claims scoped to exact fixtures/configurations and preserves prompt/test-level reproducibility where
possible.

### OWASP ASVS

- OWASP Application Security Verification Standard **5.0.0**, released 2025-05-30:
  https://owasp.org/www-project-application-security-verification-standard/

KORPUS mapping: authentication/session controls, authorization/noninterference, strict
input contracts, egress boundaries, audit integrity, configuration fail-closed tests and
security verification campaigns. The repository does not infer an ASVS certification from
unit tests; the mapping is a verification checklist substrate.

### SLSA v1.2

- SLSA specification v1.2, Approved:
  https://slsa.dev/spec/v1.2/
- Build Track basics:
  https://slsa.dev/spec/v1.2/build-track-basics
- Provenance:
  https://slsa.dev/spec/v1.2/provenance

KORPUS mapping: `scripts/slsa_provenance.py` emits an in-toto Statement using the SLSA
provenance v1 predicate and binds the completed artifact plus exact materials. The local
builder is deliberately untrusted by default and `slsa_level_claimed=false`; Build L2/L3
or Source-track claims require properties of the hosted build/source-control environment
that this package cannot self-authorize.

### OpenSSF Scorecard

- OpenSSF Scorecard checks:
  https://github.com/ossf/scorecard/blob/main/docs/checks.md

KORPUS mapping: full SHA-256 dependency pins, immutable lockfiles, digest-pinned container
bases, vulnerability-scan input generation, release integrity and explicit CI/repository
controls. `scripts/verify_dependency_locks.py` proves structural lock integrity offline;
known-vulnerability status remains UNKNOWN until OSV or an equivalent live scanner runs.

## Research basis

### Reproducible software supply chains

Chris Lamb and Stefano Zacchiroli, **Reproducible Builds: Increasing the Integrity of
Software Supply Chains**, arXiv:2104.06020 (2021):
https://arxiv.org/abs/2104.06020

Engineering consequence: source review and artifact trust are separate claims. KORPUS
therefore binds artifact bytes to source/material digests and tests deterministic package
construction rather than treating a source manifest as proof of a built ZIP.

### Retrieval-borne indirect prompt injection

Gianluca De Stefano, Lea Schönherr, Giancarlo Pellegrino, **Rag and Roll: An End-to-End
Evaluation of Indirect Prompt Manipulations in LLM-based Application Frameworks**,
arXiv:2408.05025 (2024):
https://arxiv.org/abs/2408.05025

Hongyan Chang, Ergute Bao, Xinjian Luo, Ting Yu, **Overcoming the Retrieval Barrier:
Indirect Prompt Injection in the Wild for LLM Systems**, arXiv:2601.07072 (2026):
https://arxiv.org/abs/2601.07072

Engineering consequence: retrieved text is untrusted control input, not merely content.
KORPUS normalizes Unicode/control-text variants, removes control-bearing sentences before
claims are formed, applies classification egress policy before any optional model call,
and machine-gates model composition. `test_indirect_prompt_injection_boundary.py` is the
explicit destruction proof that a poisoned retrieved sentence never reaches the composer.

## Evidence rule

External references define threats, assurance vocabulary and good practice. They never
upgrade a KORPUS gate by citation alone. A gate becomes PASS only from source-bound,
release-bound executable evidence of the required class. Independent/attested gates cannot
be generated by the same local build and remain blocked until genuinely external evidence
exists.

### Metamorphic and property-based testing

Nasser Alzahrani, Maria Spichkova, James Harland, **Application of property-based testing
tools for metamorphic testing**, arXiv:2211.12003 (2022):
https://arxiv.org/abs/2211.12003

Engineering consequence: when a single oracle is insufficient, KORPUS specifies relations
that must survive semantics-preserving transformations. The v0.6 indirect-prompt-injection
gate applies Unicode, normalization, case and separator transformations and requires the
security decision to remain invariant. This technique found a real zero-width-separator
bypass during development; the canonicalizer now evaluates both deletion and whitespace
interpretations of zero-width controls.

### Selective risk control — research boundary

Yunpeng Xu, Wenge Guo, Zhi Wei, **Selective Conformal Risk Control**,
arXiv:2512.12844 (2025):
https://arxiv.org/abs/2512.12844

Engineering consequence: selective prediction motivates explicit abstention and calibrated
risk boundaries. KORPUS does **not** claim the paper's conformal guarantees: its data and
exchangeability assumptions are not established here. The citation informs the separation
between prediction, selection/abstention and risk evidence; only KORPUS's own calibration
and negative-control gates support release claims.

### Formal methods and executable refinement

Leslie Lamport's TLA+ methodology treats behavior as state transitions constrained by
invariants. KORPUS uses reviewable TLA+ specifications plus executable bounded Python model
checkers because TLC is not included in the distribution runtime. A prose or TLA+ artifact
alone never upgrades a gate; the executable model checker must produce source-bound PASS.

## Deterministic replay execution surface

`scripts/deterministic_replay_probe.py` is invoked by `scripts/run_determinism_gate.py` for
every declared `PYTHONHASHSEED`. The gate compares its semantic SHA-256 together with the
exact JUnit outcome digest; equal test counts alone are explicitly insufficient evidence.
