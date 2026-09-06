"""Operational KORPUS environment names that intentionally live outside Settings."""

from __future__ import annotations

OPERATIONAL_VARIABLES: frozenset[str] = frozenset(
    {
        "KORPUS_BACKUP_DATABASE_URL",
        "KORPUS_BACKUP_DIR",
        "KORPUS_BACKUP_ENCRYPTION_KEY",
        "KORPUS_BACKUP_ENCRYPTION_KEY_FILE",
        "KORPUS_BACKUP_KEY_ID",
        "KORPUS_BACKUP_OBJECT_ROOT",
        "KORPUS_BACKUP_RETENTION_COUNT",
        "KORPUS_BACKUP_RETENTION_DAYS",
        "KORPUS_BACKUP_SECOND_DIR",
        "KORPUS_BACKUP_SQLITE_PATH",
        "KORPUS_DATABASE_PASSWORD_FILE",
        "KORPUS_DATABASE_URL_TEMPLATE",
        "KORPUS_MUTATION_JOBS",
        "KORPUS_MUTATION_SHARDS",
        # Ручки `scripts/run_postgres_suite.sh` (рядки 14, 44, 45, 53). Скрипт їх
        # ДОКУМЕНТУЄ, а простір імен їх не знав — тож `create_app()` валився на
        # завантаженні conftest із `unrecognised KORPUS_* environment variables`,
        # rc=4. Тобто скористатися документованим прапорцем означало зробити
        # батарею незапускною. Документація й перевірка розходились мовчки, і
        # мовчала саме перевірка, чиє призначення — ловити розходження імен.
        "KORPUS_PG_CONTAINER",
        "KORPUS_PG_KEEP",
        "KORPUS_PG_PORT",
        "KORPUS_POSTGRES_ADMIN_URL",
        "KORPUS_POSTGRES_APP_PASSWORD",
        "KORPUS_POSTGRES_APP_PASSWORD_FILE",
        "KORPUS_POSTGRES_APP_ROLE",
        "KORPUS_POSTGRES_TEST_URL",
        "KORPUS_RECOVERY_BACKUP_PATH",
        "KORPUS_RECOVERY_ENVIRONMENT_CLASS",
        "KORPUS_RECOVERY_PHASE",
        "KORPUS_RECOVERY_RESTORED_URL",
        "KORPUS_RECOVERY_RESTORE_SECONDS",
        "KORPUS_RECOVERY_SEED_URL",
        "KORPUS_RECOVERY_SOURCE_URL",
        "KORPUS_RESTORE_DATABASE_URL",
        "KORPUS_TEST_DATABASE_ADMIN_URL",
        "KORPUS_TEST_DATABASE_URL",
    }
)
