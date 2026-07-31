# Local secrets

Run `make infra-secrets` to generate `postgres_password.txt`, `minio_password.txt`, `audit_hmac_key.txt`, and `jwt_secret.txt`. Files are mode 0600, ignored by Git, and excluded from source packages. Production secrets must come from the deployment secret manager or HSM-backed service.
