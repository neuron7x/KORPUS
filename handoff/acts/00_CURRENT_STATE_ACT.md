# Act 00 — current canonical state

- Canonical baseline: `v0.1.0` (short release line: `0.1`). This is the phase-reset baseline for the next KORPUS development stage.
- Lineage: `v0.1.0` descends directly from the verified `v6.18.3` tree. Historical `v2.0.0…v6.18.3` tags remain immutable provenance and are not renumbered or rewritten.
- Runtime intent: the version reset is a release-line transition, not a functional rewrite. Runtime/application semantics inherited from `v6.18.3` remain unchanged unless a tracked diff explicitly states otherwise.
- Production authorization: `false`. The new baseline does not convert missing external evidence into PASS.
- Inherited last complete local deterministic evidence: `v6.18.3` backend 1413 PASS / 0 FAIL / 3 SKIP from 1416 collected; web 127/127 PASS; package/manifest validation PASS. These measurements remain attributed to `v6.18.3` until re-executed against `v0.1.0`.
- `v0.1.0` must carry fresh release-identity, repository, source-manifest and targeted regression evidence bound to its own commit before packaging.
- External gates remain fail-closed where exact Python 3.12.13, real PostgreSQL, production-like TEVV/reliability, independent external red-team, container/SBOM attestations and protected CI signatures are absent.

Interpretation: `v0.1.0` is the canonical engineering baseline for the next stage. It is a complete recoverable source/history package, not a claim of production authorization.
