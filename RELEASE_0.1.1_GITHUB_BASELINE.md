# KORPUS v0.1.1 — GitHub-hardened baseline

`v0.1.1` is the first `0.1` patch whose repository contract includes GitHub as the
primary collaboration/CI transport. It does not rewrite `v0.1.0` or any `v6.x` history.

## Delta

- GitHub CI, assurance, dependency-review, and release-attestation workflows.
- Full-SHA action pinning and fixed runner labels enforced by an executable policy gate.
- Checkout credentials disabled by policy; workflow permissions explicit and minimal.
- PostgreSQL suite available on the GitHub assurance path.
- Dependabot configuration for Actions, Python, and npm ecosystems.
- GitHub import/repository-policy contracts.
- First-principles engineering contract: reference path, complexity cost, negative
  controls, deterministic supply chain, and release-bound evidence.

## Non-claims

A locally valid workflow file is not proof that GitHub branch protection, secret
scanning, CodeQL, external red-team, or production environment gates are enabled.
Those remain external state and fail closed until observed on the actual repository.
