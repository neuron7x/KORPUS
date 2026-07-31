# GitLab import — KORPUS v3.0.0

## From the Git bundle

```bash
git clone KORPUS_OPERATIONAL_REFERENCE_v3.0.0.bundle korpus
cd korpus
git remote remove origin
git remote add origin git@gitlab.com:YOUR_NAMESPACE/korpus.git
git push -u origin main
git push origin --tags
```

Then configure GitLab:

1. protect `main` and release tags against direct push;
2. require successful pipeline, CODEOWNER approval and resolved discussions;
3. configure PostgreSQL/pgvector, Docker and security-capable runners;
4. replace placeholder CODEOWNER groups with real accountable owners;
5. add protected OIDC, S3, embedding, remote-anchor and deployment variables;
6. retain JUnit, coverage, assurance, SBOM and container provenance artifacts;
7. keep Codex and Claude Code in separate issue branches and worktrees;
8. allow a release only after all mutation shards merge to complete 14/14 coverage;
9. require the PostgreSQL test to run as the non-superuser `korpus_app` role;
10. require external corpus/security reviewers before any controlled-data deployment.

The source ZIP contains no Git history. The bundle contains `main`, historical tags and the `v3.0.0` release tag.
