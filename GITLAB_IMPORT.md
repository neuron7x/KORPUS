# GitLab import — KORPUS v2.0.0

## From the Git bundle

```bash
git clone KORPUS_RESEARCH_GRADE_v2.0.0.bundle korpus
cd korpus
git remote remove origin
git remote add origin git@gitlab.com:YOUR_NAMESPACE/korpus.git
git push -u origin main
git push origin --tags
```

Then configure GitLab:

1. protect `main` against direct push;
2. require successful pipeline and CODEOWNER approval;
3. configure a PostgreSQL-capable runner and retain assurance artifacts;
4. create groups matching `.gitlab/CODEOWNERS` or replace the placeholders;
5. add protected CI variables, OIDC configuration and environment approvals;
6. enable container-registry retention, secret scanning, SBOM retention and dependency alerts;
7. keep Codex and Claude Code in separate issue branches/worktrees;
8. permit release tags only after the assurance snapshot and independent review.

The source ZIP contains no Git history. The bundle contains `main` and the `v2.0.0` release tag.
