# GitHub import — KORPUS v0.1.1

Authoritative release identity: `v0.1.1`.
The canonical package contains `KORPUS_SYSTEM_v0.1.1.bundle`, which carries full Git
history and tags. Import the bundle rather than reconstructing history from ZIP files.

```bash
git clone KORPUS_SYSTEM_v0.1.1.bundle korpus
cd korpus
git checkout v0.1.1
test "$(git rev-parse HEAD)" = "$(git rev-parse v0.1.1^{commit})"
```

Create the GitHub repository, add it as `origin`, then publish the existing history.
For a new empty remote, `git push --mirror origin` preserves branches and tags. Review
refs before using `--mirror`; it intentionally synchronizes every local ref.

After import, create/protect `main` according to
`docs/operations/GITHUB_REPOSITORY_POLICY.md`. Repository-side settings are external
state and are not claimed as configured merely because this document exists.
