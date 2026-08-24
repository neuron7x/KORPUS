# KORPUS v0.9.7 — Evidence & Governance Reference

## Evidence classes
- **ANCHORED** — executed/measured and source/release bound.
- **LOCAL_STATIC** — executable configuration contract; not live behavior.
- **LOCAL_SYNTHETIC** — real local execution on synthetic fixture; not production-domain evidence.
- **EXTERNAL_REQUIRED** — cannot be validly self-created by the local engineering process.
- **UNKNOWN** — no admissible evidence.

## Core evidence
- Regression: 2345/2345; 64 shards; 0 failures/errors; 1 real-PostgreSQL skip.
- Mutation: 349/349 killed; 0 survivor/invalid/error.
- Web: 146/146; browser 5/5.
- Determinism seeds: `0, 1, 42, 31337`; identical semantic replay and outcome digests.
- Operational engineering gate: PASS; production authorization false.
- Hard predicates: 14/14 software-ready; 0/14 externally satisfied.

## Authority separation
- Model self-judgment cannot satisfy HUMAN PEC authority.
- Local self-signing cannot satisfy independent-assessor predicates.
- Static RLS cannot satisfy live PostgreSQL/RLS.
- Synthetic eval/load cannot satisfy real-domain TEVV or production-like load.
- Workflow existence cannot satisfy hosted execution evidence.

## Portable evidence
`handoff/evidence/current/` contains current raw regression, mutation, web, browser, determinism, local eval/migration/scale, infrastructure and release evidence. `MANIFEST.json` SHA-256 binds every copied file.
