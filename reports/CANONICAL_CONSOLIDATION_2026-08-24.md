# Canonical consolidation report

Date: 2026-08-24  
Canonical root: `/home/neuro7/Desktop/Ядро основний проект Корпус`

## Result

The recovery-bundle wrapper, nested repository wrapper, transport archives,
recursive historical source copies and runtime language caches were removed.
The directory itself is now the single writable KORPUS source-of-truth tree.

The uploaded v0.9.7 baseline contained 2,151 files. The recovered tree contained
all baseline paths: 2,134 byte-identical, 17 modified, zero missing, plus 1,075
session additions. The 17 original versions and the complete recovery manifest
are retained under `LINEAGE/` and `reports/recovery/`; retaining another 2,134
identical files was unnecessary.

All four observed ZIP classes were integrity-tested before removal: the outer
chat recovery bundle, uploaded v0.9.7 baseline, v0.8.1/v0.8.0/v0.6.1 lineage
snapshots, and the audit package. Audit contents were checked against their
already extracted copies; the one missing checksum inventory was restored.

## Canonical layout

- `apps/`: API and web applications.
- `packages/` and `contracts/`: shared and external contracts.
- `config/`, `infra/`, `deploy/`: desired state and deployment definitions.
- `evals/`, `formal/`: evaluation and formal assurance assets.
- `docs/`, `handoff/`: architecture, governance, operations and handoff.
- `reports/`, `candidate_evidence/`, `var/`: evidence and retained run outputs.
- `LINEAGE/`: provenance metadata and minimal reconstruction delta, not another
  competing source tree.
- `scripts/`: reproducible build, validation, recovery and assurance tooling.

## Verification performed

- ZIP CRC/integrity checks and SHA-256 comparisons before consolidation.
- Recovery tree vs uploaded v0.9.7 classification: no baseline path loss.
- Repository validation: 114/114 requirements; 99/99 audit findings classified.
- Source manifest: 1,200 files, verified after regeneration.
- Import cycle, module budget, release identity and GitHub Actions policy checks.
- Backend suite: one initial generated-register drift; after regeneration the
  parity test passed. The complete run otherwise passed with one intentional skip.
- Web lint/validation: PASS.
- Web tests: 146/146 PASS.
- Web production build: PASS.

## Honest limits

- The recovered package did not contain `.git`; no original commit history or
  signed tag can be reconstructed from filesystem bytes alone.
- Full repository Ruff currently reports 2,617 inherited findings. They predate
  this consolidation and were not bulk-auto-fixed because that would mix a large
  behavioral rewrite into a provenance/packaging operation.
- External PostgreSQL, cloud, load, signing and production-only gates were not
  executed. Production promotion is not claimed.
