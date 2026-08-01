# PostgreSQL backup and restore runbook — v4

## Killable invariants

- `pg_dump` bytes flow directly into streaming AES-256-GCM encryption; the backup path never receives a plaintext dump.
- The 32-byte encryption key is external to the repository and backup directory.
- `KORPUS_BACKUP_KEY_ID` is mandatory for both backup and restore.
- Manifest schema `korpus-postgres-backup-v4` binds filename, cipher, ciphertext/plaintext hashes, byte counts and key ID.
- The manifest is authenticated with a domain-separated HMAC derived from the backup key.
- Restore rejects a changed manifest, wrong key ID, wrong filename, truncated ciphertext, wrong ciphertext hash, wrong plaintext hash or wrong plaintext size.
- Restore targets an explicitly supplied database, runs through `pg_restore --single-transaction`, and verifies the exact Alembic head.
- A recovery proof is incomplete until the restored database passes non-superuser RLS and audit-head verification.
- PostgreSQL backup does not replace S3 object-version replication or remote audit-anchor retention; these remain independent durability domains.

## Backup

```bash
export KORPUS_BACKUP_DATABASE_URL='postgresql://backup_role:...@db/korpus'
export KORPUS_BACKUP_ENCRYPTION_KEY_FILE='/run/secrets/backup_aes256_key.hex'
export KORPUS_BACKUP_KEY_ID='kms-key-version-2026-08'
export KORPUS_BACKUP_DIR='/secure/backups/korpus'
scripts/backup_postgres.sh
```

The key file must contain exactly 64 hexadecimal characters. The script returns one encrypted filename such as:

```text
korpus-20260801T081522.123456Z.dump.enc
```

Its adjacent `.json` manifest is required for restore. Replicate both files atomically to immutable off-site storage.

## Restore drill

```bash
export KORPUS_RESTORE_DATABASE_URL='postgresql://restore_admin:...@db/korpus_restore'
export KORPUS_BACKUP_ENCRYPTION_KEY_FILE='/run/secrets/backup_aes256_key.hex'
export KORPUS_BACKUP_KEY_ID='kms-key-version-2026-08'
scripts/restore_postgres.sh /secure/backups/korpus/korpus-20260801T081522.123456Z.dump.enc

export KORPUS_DATABASE_URL='postgresql+psycopg://restore_admin:...@db/korpus_restore'
export KORPUS_POSTGRES_APP_ROLE='korpus_app'
export KORPUS_POSTGRES_APP_PASSWORD_FILE='/run/secrets/postgres_app_password'
python scripts/prepare_postgres_role.py

export KORPUS_POSTGRES_TEST_URL='postgresql+psycopg://korpus_app:...@db/korpus_restore'
python scripts/verify_postgres_restore.py
```

Run the drill on a clean database after every schema change and on the declared recovery cadence. Record restore duration against the declared RTO. A successful backup job or `pg_restore` exit code alone is not recovery evidence.
