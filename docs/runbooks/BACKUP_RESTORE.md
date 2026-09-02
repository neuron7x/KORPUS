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

## SQLite (the deployment that is actually running)

`serve-public` runs on SQLite, not PostgreSQL. The `pg_dump` path above covers the
deployment KORPUS is *designed* for; this covers the one it is *running*, and losing the
file is not a recovery-time incident but a repeat of the five-hour import.

**ВИМІРЯНО 2026-09-02.** Ці команди НЕ були executable as written, і фраза стояла тут
попри це. `KORPUS_BACKUP_SQLITE_PATH` вказував на `$PWD/var/korpus-ml.db` — файла з
таким іменем немає, а коли він був, журнал вироків від 30.08 каже, що він «лишився
ПОРОЖНІМ (4 КБ)». Той самий хибний дефолт стояв і в `scripts/backup_sqlite.sh:24`, тож
`make backup-sqlite` виходив із `rc=66 no database at …`, теки `var/backups/sqlite/` не
існувало, і **бекапу живого корпусу на 276 МБ не робилось жодного разу**.

Полагоджено обидва місця, і прогоном доведено: архів 229 МБ, відновлено, і відновлена
база звірена ПРЕДМЕТОМ, а не розміром — 256 документів, 256 версій, 31464 прольоти й
однаковий хеш усіх `source_hash`. Розходження дефолтів тепер ловить
`make corpus-path-declarations` усередині `validate`.

Back up — a consistent snapshot while the site is still answering (WAL mode):

```bash
# Обидва шляхи — дефолти скрипта; тут вони названі, щоб рецепт читався сам собою.
export KORPUS_BACKUP_SQLITE_PATH="$PWD/var/runtime/corpus-v6-20260807/korpus.db"
export KORPUS_BACKUP_OBJECT_ROOT="$PWD/var/runtime/corpus-v6-20260807/objects"
export KORPUS_BACKUP_ENCRYPTION_KEY_FILE="$HOME/.local/state/korpus-public/backup.key"
export KORPUS_BACKUP_KEY_ID=ops
export KORPUS_BACKUP_DIR="$HOME/korpus-backups"     # OUTSIDE the repo tree
[ -f "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" ] || {
  mkdir -p "$(dirname "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE")"
  python3 -c "import secrets;print(secrets.token_hex(32))" > "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE"
  chmod 600 "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE"; }
scripts/backup_sqlite.sh                             # prints the encrypted backup path
```

Restore — and prove it answers, because an empty corpus restores *cleanly*:

```bash
scripts/restore_sqlite.sh <backup.enc> "$PWD/var/restored"
```

`restore_sqlite.sh` exits non-zero and prints `unusable` if the restored database holds no
approved versions or spans — a file that opens is not a restore.

**Cadence:** daily while the corpus is being imported, then before every corpus change.
**Recovery criterion:** the restored copy answers a known question with citations. The key
file lives outside the repository tree — a backup encrypted with a key sitting beside it is
one `rm -rf` from being both gone and unrecoverable.
