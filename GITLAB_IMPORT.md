# GitLab import — KORPUS v5.0.0

## From the Git bundle

```bash
git clone KORPUS_FINAL_ASSURANCE_v5.0.0.bundle korpus
cd korpus
git remote remove origin
git remote add origin git@gitlab.com:YOUR_NAMESPACE/korpus.git
git push -u origin main
git push origin --tags
```

## Required GitLab controls

1. Protect `main` and release tags; prohibit direct pushes.
2. Require successful pipelines, CODEOWNER approval, resolved discussions and independent reviewer sign-off.
3. Use isolated trusted runners for PostgreSQL/pgvector, Kubernetes validation and rootless BuildKit.
4. Replace placeholder CODEOWNER groups with accountable system, security, data and reliability owners.
5. Store OIDC, S3, PostgreSQL, backup/KMS, embedding, audit-anchor and deployment credentials as protected external secrets.
6. Retain JUnit, coverage, eval, mutation, migration, SBOM, scan, provenance and recovery artifacts.
7. Require PostgreSQL tests under a non-superuser application role with `FORCE RLS` active.
8. Require all six mutation shards and completeness merge: 26/26 selected critical mutants.
9. Generate signed provenance and promote immutable registry digests; never deploy mutable tags.
10. Keep Codex and Claude Code in separate issue branches/worktrees; the implementing agent cannot approve or merge its own change.
11. Require blind real-corpus TEVV, independent pentest/red-team and formal risk acceptance before controlled-data deployment.
12. Treat `docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json` as the debt source of truth; no status may be changed without immutable acceptance evidence.

The source ZIP contains no Git history. The Git bundle contains the complete history, `main` and release tag `v5.0.0`.
