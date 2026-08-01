# Security policy

Do not open a public issue containing credentials, restricted documents, personal data, exploit details, audit keys, backup keys, raw database dumps or production topology.

Report privately to the accountable security owner with:

- affected commit, image digest, migration and corpus release;
- minimal reproduction using synthetic data;
- identity, role and corpus context;
- observed versus expected killable invariant;
- bounded evidence of exposure without collecting additional sensitive content.

Supported branch: protected `main` and the latest release tag.

A vulnerability is closed only after:

1. a reproducing negative test exists;
2. the root cause is removed rather than suppressed;
3. an independent reviewer verifies the fix;
4. adversarial/mutation/regression gates pass;
5. migration, recovery and packaging evidence remains valid;
6. a new content-addressed release artifact is produced.

Secrets must enter runtime through protected files or a deployment secret manager. They must not appear in Compose values, GitLab logs, build arguments, images, source archives or assurance reports.
