# Act 00 — current canonical state

- Canonical release: `v6.15.0` ACT-012 structured external-red-team evidence and recomputed verdict line.
- Recovery base: verified `v6.8.2` package, Git HEAD `4a810ed609fd40fc4690411afb6d545ac4095b38`.
- Production authorization: `false`.
- Last complete source-bound test campaign belongs to `v6.8.2`: 1347 tests, 0 failures, 0 errors, 3 skipped; line coverage 0.9172; branch coverage 0.7891.
- Last complete mutation campaign belongs to `v6.8.2`: full catalogue PASS (`277/277` killed in the preserved release evidence).
- `v6.12.0` changes invalidate those measurements as current-release evidence until fresh gates execute; they remain historical baseline only.
- Current locally verified static gates: desired-state, import graph, release identity, module budget, requirements register, doctrine catalogue, repository, infrastructure, Kubernetes.
- Environment-limited gates remain unexecuted or FAIL-closed where the required tool/runtime is absent: ruff, mypy, full pytest/coverage in one uninterrupted campaign, live PostgreSQL, production-like TEVV/load/recovery, trusted independent red-team, complete scanner/container-SBOM attestation.

Interpretation: `v6.15.0` is a canonical engineering continuation point, not a production authorization. Any agent must regenerate source-bound evidence after changing tracked source and must not reuse `v6.8.2` PASS artifacts as evidence for `v6.15.0`.
