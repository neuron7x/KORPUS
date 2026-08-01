# KORPUS FINAL ASSURANCE v5.0.0 — package index

## Primary artifacts

- complete committed source tree;
- Git history and release tag in a separate Git bundle;
- deterministic repository manifest and SHA-256 files;
- source-bound assurance snapshot;
- complete v4 extended audit in PDF, DOCX, Markdown, JSON, CSV and original package ZIP;
- v5 99-finding closure register in JSON/CSV/Markdown;
- technical debt, TEVV, authorization, system card, risk, security and operations documents.

## Machine-readable sources of truth

- `REPOSITORY_MANIFEST.json` — package file inventory and root hash;
- `reports/ASSURANCE_SNAPSHOT.json` — content hashes of JUnit, coverage, eval, mutation, migration, scale, operations, supply-chain and deployment-validation evidence;
- `reports/RESEARCH_ASSURANCE_REPORT.json` — composed local gate result;
- `docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json` — complete finding status;
- `config/operations/desired-state-v5.json` — desired-state hashes;
- `contracts/openapi.json` — frozen API contract;
- `var/` is execution scratch space and is not release authority.

## Interpretation boundary

The package is a complete engineering baseline for the frozen repository scope. It does not assert discovery of every possible vulnerability and does not self-authorize production. External evidence remains mandatory where identified in the closure and debt registers.

## Local agent handoff

- `handoff/START_HERE_UA.md`
- `handoff/acts/`
- `handoff/plans/`
- `handoff/prompts/`
- `handoff/machine/`
- `scripts/verify_handoff_contract.py`
- `RELEASE_V5_1.md`
