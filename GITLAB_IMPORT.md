# GitLab import — KORPUS v4.0.0

## From the Git bundle

```bash
git clone KORPUS_INFRA_HARDENED_v4.0.0.bundle korpus
cd korpus
git remote remove origin
git remote add origin git@gitlab.com:YOUR_NAMESPACE/korpus.git
git push -u origin main
git push origin --tags
```

## Required GitLab controls

1. Protect `main` and release tags; prohibit direct push.
2. Require successful pipelines, CODEOWNER approval and resolved discussions.
3. Use isolated runners capable of PostgreSQL service jobs and rootless BuildKit.
4. Replace placeholder CODEOWNER groups with accountable owners.
5. Add protected file variables for PostgreSQL, MinIO/S3, backup key, OIDC, embeddings, remote anchor and deployment credentials.
6. Retain JUnit, coverage, assurance, SBOM, image scan and recovery-drill artifacts.
7. Require the PostgreSQL test to execute under non-superuser `korpus_app` with `FORCE RLS` active.
8. Require all three mutation shards and the completeness merge: 14/14 critical mutants.
9. Promote built registry digests into deployment manifests; do not deploy mutable tags directly.
10. Keep Codex and Claude Code in separate issue branches/worktrees; neither agent may merge its own output.
11. Require independent corpus/security authorization before controlled-data deployment.

The source ZIP contains no Git history. The bundle contains `main`, historical tags and release tag `v4.0.0`.
