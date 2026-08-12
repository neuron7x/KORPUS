# KORPUS 0.1 baseline

`v0.1.0` starts a new development phase without rewriting project history.

## Canonical lineage

- Parent engineering release: `v6.18.3`.
- New canonical baseline: `v0.1.0` (short line: `0.1`).
- Historical tags and their evidence remain immutable.
- The reset changes release identity and phase semantics; it does not silently relabel historical measurements as fresh `v0.1.0` measurements.

## Verification contract

A `v0.1.0` distribution is canonical only when release identity, repository contract, source manifest, package manifest, Git bundle and targeted regression checks are bound to the tagged commit. Missing environment-dependent or production-only gates remain fail-closed.
