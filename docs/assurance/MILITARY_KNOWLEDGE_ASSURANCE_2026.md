# KORPUS Military Knowledge Assurance — 2026 engineering doctrine

## Mission boundary
KORPUS is an evidence-bound information and training system for military learners. It is not an autonomous command system and does not convert retrieval confidence into authority to act. The product objective is **time-to-verified-understanding under access, freshness and evidence constraints**.

## Tested-system identity
A score is admissible only for the exact tested system: source tree + release + configuration + harness + dataset + environment + resource budget. A materially different configuration is a different system. Historical evidence is lineage, not current proof.

## Assurance algebra
Production admission is conjunctive. Access leakage, stale governing authority, unsupported claims, citation corruption, missed mandatory abstention, source-identity mismatch, or accepted offline rollback are hard failures. A higher average accuracy cannot cancel any of them.

For a hard-failure class with `f` failures in `n` observations, KORPUS reports the Wilson 95% interval. `f=0` is not interpreted as zero risk. Production admission requires both zero observed hard failures and an upper confidence bound below the configured risk ceiling.

## Four-layer T&E
1. **Model/retrieval T&E:** retrieval recall, authority ordering, contradiction handling, citations, abstention, deterministic replay.
2. **Human-systems T&E:** calibrated trust, cognitive load, comprehension of source status, comprehension of abstention, time to verified answer.
3. **Systems-integration T&E:** identity/RLS, offline signatures, rollback protection, audit, failure recovery, interoperability.
4. **Operational T&E:** real-domain material, representative devices/networks, degraded/offline conditions, instructor-supervised trials.

A local synthetic suite can establish invariants and kill regressions. It cannot satisfy layers 2–4 by declaration.

## Inference invariants
- Authorization precedes retrieval.
- Governing temporal authority precedes similarity.
- Retrieval scores rank evidence; they do not establish truth.
- Claims must be source-bound and citation-verifiable.
- Contradiction or insufficient evidence produces an explicit non-answer state.
- Audience adaptation may alter explanation style but not claim/evidence identity.
- Offline mode exposes freshness and refuses invalid, revoked, forked or rolled-back packages.

## Evaluation protocol
Every evaluation record includes: claim, tested-system identity, harness, resource budget, validity checks, outcome, transcript/evidence, uncertainty, failure class, and whether the run is independent/real-domain/operationally representative. Broken cases are excluded only through an auditable adjudication record, never silently.

## Change discipline
Optimization is accepted only when differential or metamorphic tests establish preserved semantics. Architecture changes require regression tests and mutation targets. Release promotion occurs only after current evidence is regenerated against the exact source digest.

## Primary references
The canonical machine-readable registry is
`config/assurance/ASSURANCE_SOURCE_REGISTRY_2026.json`; its human-readable and BibTeX
renders are `docs/research/BIBLIOGRAPHY_2026.md` and
`docs/research/korpus-engineering-2026.bib`.
