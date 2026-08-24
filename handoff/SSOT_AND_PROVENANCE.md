# SSOT and provenance contract

The authoritative object is the frozen repository state plus its manifests and executable evidence. No assistant, developer narrative, README claim or green unrelated test may override a failed machine gate.

## Precedence

1. Git object identity and signed/protected tag where available.
2. `SOURCE_MANIFEST.json`, source-tree digest and release checksums.
3. Runtime code, migrations, schemas and controlled configuration.
4. `reports/` evidence bound to the source state.
5. `docs/audit/closure/*.json` and `handoff/machine/*.json`.
6. Human-readable acts and runbooks.

## Change rule

A claim changes only through a new branch, review, commit, relevant tests/evals/mutations/migrations, regenerated evidence, manifest and release. Agents must report every gate not executed.

## Scope limit

The package is a verified engineering baseline and local-development handoff. It is not ordinary or restricted military production authorization.
