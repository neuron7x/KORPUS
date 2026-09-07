# Merge Guide

Suggested branch: `proposal/korpus-capability-gateway-v1-20260904`.

This theory package is low-conflict because it adds only a currently absent proposal subtree.

```bash
git switch main
git pull --ff-only
git switch -c proposal/korpus-capability-gateway-v1-20260904
unzip KORPUS_CAPABILITY_GATEWAY_THEORY_BRANCH_578f4ea9.zip -d .
git status --short
git diff -- docs/proposals/korpus-capability-gateway-v1
```

Verify that no path outside the proposal subtree changed. Rebase/update from current `main`
before merge. If current source/distribution manifest rules include documentation, regenerate
them using the **live** repository procedure; this package deliberately does not modify those
existing files.

Suggested theory commit:
`docs: specify KORPUS capability gateway v1`

After the proposal is merged, the coding agent still performs WP0 against live main.
