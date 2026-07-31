# GitLab import

## From the Git bundle

```bash
git clone KORPUS_FULL_REPOSITORY_v1.0.0.bundle korpus
cd korpus
git remote remove origin
git remote add origin git@gitlab.com:YOUR_NAMESPACE/korpus.git
git push -u origin main
git push origin --tags
```

Then configure GitLab:

1. protect `main` against direct push;
2. require successful pipeline and CODEOWNER approval;
3. create groups matching `.gitlab/CODEOWNERS` or replace the placeholders;
4. add protected CI variables and runner tags;
5. enable container registry retention, secret scanning, SBOM retention and environment approvals;
6. keep Codex and Claude Code in separate issue branches/worktrees.

The source ZIP contains no Git history. The bundle contains the initial `main` commit and `v1.0.0` tag.
