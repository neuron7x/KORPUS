# Local secrets

Run `make infra-secrets` before `make infra-up`. Generated files are mode `0600` and ignored by Git.

Credential domains:

- `postgres_admin_password.txt` — migration/role bootstrap only;
- `postgres_app_password.txt` — non-superuser runtime role;
- `minio_root_password.txt` — MinIO bootstrap administrator only;
- `minio_app_access_key.txt` and `minio_app_secret_key.txt` — prefix-scoped API identity without object deletion;
- `audit_hmac_key.txt` — local audit-chain and checkpoint MAC key;
- `jwt_secret.txt` — local JWT mode only;
- `metrics_token.txt` — protects the metrics endpoint;
- `backup_encryption_key.txt` — local AES-256-GCM backup key; its key ID is supplied separately through `KORPUS_BACKUP_KEY_ID`.

Production must use a deployment secret manager or HSM/KMS-backed service, separate operators and rotation schedules. Never reuse these local files or commit them.
