# Local secrets

Run `make infra-secrets` before `make infra-up`. The local secret directory is mode `0700`; compose-readable files inside it are mode `0644` because capability-dropped containers cannot read host-owned `0600` files. The directory prevents other host users from traversing to those files. Generated secrets are ignored by Git.

Credential domains:

- `postgres_admin_password.txt` — migration/role bootstrap only;
- `postgres_app_password.txt` — ordinary non-superuser runtime role; cannot write review-controlled version state;
- `postgres_review_password.txt` — separate non-superuser review-transition role, mounted only into the API and migration bootstrap;
- `postgres_identity_password.txt` — isolated RLS identity broker login; used only to bind target app/review transactions to server-validated claims and granted no direct corpus-table access;
- `minio_root_password.txt` — MinIO bootstrap administrator only;
- `minio_app_access_key.txt` and `minio_app_secret_key.txt` — prefix-scoped API identity without object deletion;
- `audit_hmac_key.txt` — local audit-chain and checkpoint MAC key;
- `jwt_secret.txt` — local JWT mode only;
- `metrics_token.txt` — protects the metrics endpoint;
- `backup_encryption_key.txt` — local AES-256-GCM backup key; its key ID is supplied separately through `KORPUS_BACKUP_KEY_ID`.

Production must use a deployment secret manager or HSM/KMS-backed service, separate operators and rotation schedules. Never reuse these local files or commit them.
