# Review and release protocol

## Document review

```text
quarantined
 -> metadata_reviewed
 -> content_reviewed
 -> approved
```

Any non-rejected state may be rejected only where the transition table permits. Approval requires a non-unknown authority class and an identity with `document:approve`.

A production reviewer must be appointed outside the software and recorded through organizational policy. Repository roles are technical permissions, not proof of legal authority.

## Code release

1. Issue contains acceptance predicates and trust-boundary impact.
2. Agent works in an isolated worktree.
3. Unit, integration, negative and frozen evaluation tests pass.
4. Secret scan, dependency audit and SBOM complete.
5. Independent reviewer verifies diff and evidence.
6. Protected merge request merges to `main`.
7. Image is built once, identified by digest, signed and promoted without rebuild.
8. Staging smoke test runs against the exact artifact.
9. Production promotion requires a human gate and rollback command.
