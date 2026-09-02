# Local secrets

Run `make infra-secrets` before `make infra-up`. Generated files are mode `0644`, inside a
directory that is mode `0700`, and ignored by Git.

**ВИПРАВЛЕНО 2026-09-02.** Тут стояло `0600`, а генератор ставить `0644` — і саме він
має рацію. Захистом є ТЕКА: жоден інший користувач не пройде крізь `0700`, тож режим
самого файла проти нього не боронить нічого. Натомість контейнер, що скидає всі
спроможності, НЕ МОЖЕ прочитати файл `0600`, якого не володіє, навіть як root, бо
`DAC_OVERRIDE` серед скинутих. Виміряно 2026-08-06: з `0600` minio вмирав на «Unable
to validate credentials inherited from the secret file(s)», і в такому стані був
КОЖЕН сервіс compose, що читає секрет — саме тому топологія ніколи не піднімалась.
Повне обґрунтування — у `scripts/init_local_secrets.sh`, і воно тут не дублюється:
друге оголошення того самого факту розійшлося б знову, як розійшлось це.

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
