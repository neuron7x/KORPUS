# Реєстр вимог КОРПУСу

Згенеровано `scripts/export_requirements.py`. Не редагувати вручну — джерело це `korpus/infrastructure_requirements.py` та `korpus/controlled_requirements.py`.

Усього вимог: **157**.

Кожна має ідентифікатор, за яким її можна процитувати в аудиті, позначити як прийнятий ризик із названим власником, зіставити з мутантом і порахувати. До 05.08.2026 їх не було: перевірка існувала як рядок, дописаний у місці збою.

## backup

| id | вимога | чому |
|---|---|---|
| `backup.backup_postgres.encryption_key_required` | backup_postgres.sh requires the backup encryption key | — |
| `backup.key_identity_mandatory` | backup and restore both require the encryption key identity | a backup encrypted under an unknown key cannot be restored deliberately |
| `backup.manifest.authenticated_schema` | the backup manifest carries the current authenticated schema | — |
| `backup.manifest_verified_on_both_sides` | backup and restore both verify the authenticated manifest | — |
| `backup.no_file_flag` | pg_dump is never given --file | on PostgreSQL 17 --file=- wrote a file named '-' and encrypted nothing |
| `backup.restore_postgres.encryption_key_required` | restore_postgres.sh requires the backup encryption key | — |
| `backup.streams_to_stdout` | pg_dump streams into encryption without a plaintext file | a plaintext dump on disk is the corpus, unencrypted, for as long as it exists |

## build

| id | вимога | чому |
|---|---|---|
| `dockerfile.api.fixed_non_root_uid` | the API image runs as a fixed non-root UID | — |
| `dockerfile.api.hashed_lock` | the API image installs the runtime lock with pinned hashes | a version pin says which release; a hash says which bytes |
| `dockerfile.web.reproducible_non_root` | the web image builds reproducibly and runs non-root | — |
| `dockerignore.env` | .dockerignore excludes .env | anything not excluded is copied into the image and shipped |
| `dockerignore.git` | .dockerignore excludes .git | anything not excluded is copied into the image and shipped |
| `dockerignore.infra_secrets_*.txt` | .dockerignore excludes infra/secrets/*.txt | anything not excluded is copied into the image and shipped |
| `dockerignore.node_modules` | .dockerignore excludes node_modules | anything not excluded is copied into the image and shipped |

## controlled-environment

| id | вимога | чому |
|---|---|---|
| `controlled.audit_anchor_authentication` | controlled environments require audit anchor authentication | — |
| `controlled.audit_key` | production audit key is missing or weak | — |
| `controlled.browser_authentication` | controlled environments require browser OIDC/BFF authentication | — |
| `controlled.browser_session_key` | controlled browser sessions require a strong session key | — |
| `controlled.browser_settings` | browser OIDC settings are missing: authorization endpoint, token endpoint, client id, redirect URI | — |
| `controlled.calibrated_answers` | validated calibration profile is required | — |
| `controlled.corpus_governance_profile` | controlled environments require a corpus governance profile | — |
| `controlled.corpus_governance_profile_digest` | controlled environments require a corpus governance profile digest | — |
| `controlled.durable_ingestion` | controlled environments require durable asynchronous ingestion | — |
| `controlled.entitlement_profile` | controlled environments require a server-side entitlement profile | — |
| `controlled.entitlement_profile_digest` | controlled environments require an entitlement profile digest | — |
| `controlled.explicit_https_cors` | controlled CORS origins must be explicit HTTPS origins | — |
| `controlled.explicit_trusted_hosts` | controlled environments require explicit trusted hosts | — |
| `controlled.https_otlp_endpoint` | controlled OTLP endpoints must use HTTPS | — |
| `controlled.https_redirect_uri` | controlled OIDC redirect URI must use HTTPS | — |
| `controlled.https_s3_endpoint` | controlled S3 endpoints must use HTTPS | — |
| `controlled.jwks_url` | OIDC JWKS URL is required | — |
| `controlled.malware_scanning` | controlled environments require fail-closed malware scanning | — |
| `controlled.metrics` | controlled environments require operational metrics | — |
| `controlled.metrics_authentication` | controlled environments require an authenticated metrics endpoint | — |
| `controlled.migration_managed_schema` | controlled environments require migration-managed schema | — |
| `controlled.object_governance_retention` | controlled object storage requires governance retention | — |
| `controlled.oidc` | OIDC authentication is required in controlled environments | — |
| `controlled.parser_isolation` | controlled environments require parser process isolation | — |
| `controlled.postgresql` | controlled environments require PostgreSQL | — |
| `controlled.remote_audit_anchor` | controlled environments require a remote HTTP audit anchor | — |
| `controlled.reviewer_registry` | controlled environments require a reviewer credential registry | — |
| `controlled.reviewer_registry_digest` | controlled environments require a reviewer registry digest | — |
| `controlled.reviewer_separation` | controlled environments require reviewer separation | — |
| `controlled.secure_cookie` | controlled browser session cookies must be Secure | — |
| `controlled.source_signatures` | controlled environments require detached source signatures | — |
| `controlled.source_trust_profile` | controlled environments require a source trust profile | — |
| `controlled.source_trust_profile_digest` | controlled environments require a source trust profile digest | — |
| `controlled.verified_tls` | controlled PostgreSQL connections require sslmode=verify-full | — |

## docker-compose

| id | вимога | чому |
|---|---|---|
| `compose.api.credential.minio_app_access_key` | the API carries its own minio_app_access_key | — |
| `compose.api.credential.minio_app_secret_key` | the API carries its own minio_app_secret_key | — |
| `compose.api.depends_on.clamav` | the API waits for clamav | — |
| `compose.api.depends_on.migrate` | the API waits for migrate | — |
| `compose.api.depends_on.minio-init` | the API waits for minio-init | — |
| `compose.api.depends_on.otel-collector` | the API waits for otel-collector | — |
| `compose.api.egress_network` | the API has a dedicated egress network | — |
| `compose.api.exact_image_tag` | api pins an exact image tag | latest is whatever the registry served that morning |
| `compose.api.ingestion_mode` | the API uses durable asynchronous ingestion | — |
| `compose.api.init` | api runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.api.malware_scan` | the API scans uploads through clamd | — |
| `compose.api.no_host_ports` | api publishes no host ports | a published port is reachable from wherever the host is |
| `compose.api.no_minio_root` | the API never mounts MinIO root credentials | root credentials make every object-storage control advisory |
| `compose.api.no_new_privileges` | api sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.api.object_store_mode` | the API uses S3-compatible object storage | — |
| `compose.api.parser_sandbox` | the API isolates the parser in its own process | the parser reads bytes chosen by whoever uploaded them |
| `compose.api.postgres_url` | the API connects through the psycopg PostgreSQL driver | — |
| `compose.api.present` | the api service is defined | — |
| `compose.api.read_only_root` | the API root filesystem is read-only | a writable root turns a parser bug into a persistent implant |
| `compose.api.resource_ceiling` | api declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.api.s3_path_style` | the API addresses S3 by path style | — |
| `compose.api.schema_mode` | the API runs migration-managed schema | — |
| `compose.api.unprivileged` | api does not run privileged | a privileged container is the host |
| `compose.clamav.exact_image_tag` | clamav pins an exact image tag | latest is whatever the registry served that morning |
| `compose.clamav.init` | clamav runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.clamav.no_host_ports` | clamav publishes no host ports | a published port is reachable from wherever the host is |
| `compose.clamav.no_new_privileges` | clamav sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.clamav.present` | the clamav service is defined | — |
| `compose.clamav.resource_ceiling` | clamav declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.clamav.unprivileged` | clamav does not run privileged | a privileged container is the host |
| `compose.migrate.exact_image_tag` | migrate pins an exact image tag | latest is whatever the registry served that morning |
| `compose.migrate.init` | migrate runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.migrate.no_host_ports` | migrate publishes no host ports | a published port is reachable from wherever the host is |
| `compose.migrate.no_new_privileges` | migrate sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.migrate.present` | the migrate service is defined | — |
| `compose.migrate.resource_ceiling` | migrate declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.migrate.unprivileged` | migrate does not run privileged | a privileged container is the host |
| `compose.minio-init.exact_image_tag` | minio-init pins an exact image tag | latest is whatever the registry served that morning |
| `compose.minio-init.init` | minio-init runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.minio-init.no_host_ports` | minio-init publishes no host ports | a published port is reachable from wherever the host is |
| `compose.minio-init.no_new_privileges` | minio-init sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.minio-init.present` | the minio-init service is defined | — |
| `compose.minio-init.resource_ceiling` | minio-init declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.minio-init.unprivileged` | minio-init does not run privileged | a privileged container is the host |
| `compose.minio.exact_image_tag` | minio pins an exact image tag | latest is whatever the registry served that morning |
| `compose.minio.init` | minio runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.minio.no_host_ports` | minio publishes no host ports | a published port is reachable from wherever the host is |
| `compose.minio.no_new_privileges` | minio sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.minio.present` | the minio service is defined | — |
| `compose.minio.resource_ceiling` | minio declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.minio.unprivileged` | minio does not run privileged | a privileged container is the host |
| `compose.network.backend.internal` | the backend network is internal | an external bridge exposes every service on it to the host network |
| `compose.network.edge.internal` | the edge network is internal | an external bridge exposes every service on it to the host network |
| `compose.otel-collector.exact_image_tag` | otel-collector pins an exact image tag | latest is whatever the registry served that morning |
| `compose.otel-collector.init` | otel-collector runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.otel-collector.no_host_ports` | otel-collector publishes no host ports | a published port is reachable from wherever the host is |
| `compose.otel-collector.no_new_privileges` | otel-collector sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.otel-collector.present` | the otel-collector service is defined | — |
| `compose.otel-collector.resource_ceiling` | otel-collector declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.otel-collector.unprivileged` | otel-collector does not run privileged | a privileged container is the host |
| `compose.postgres.capabilities` | postgres adds no Linux capability beyond the documented set | — |
| `compose.postgres.exact_image_tag` | postgres pins an exact image tag | latest is whatever the registry served that morning |
| `compose.postgres.init` | postgres runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.postgres.no_host_ports` | postgres publishes no host ports | a published port is reachable from wherever the host is |
| `compose.postgres.no_new_privileges` | postgres sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.postgres.present` | the postgres service is defined | — |
| `compose.postgres.resource_ceiling` | postgres declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.postgres.unprivileged` | postgres does not run privileged | a privileged container is the host |
| `compose.web.edge_only` | web is isolated to the internal edge network | — |
| `compose.web.exact_image_tag` | web pins an exact image tag | latest is whatever the registry served that morning |
| `compose.web.init` | web runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.web.no_host_ports` | web publishes only on loopback | a published port is reachable from wherever the host is |
| `compose.web.no_new_privileges` | web sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.web.present` | the web service is defined | — |
| `compose.web.resource_ceiling` | web declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.web.unprivileged` | web does not run privileged | a privileged container is the host |
| `compose.worker.clamav` | the worker waits for ClamAV | — |
| `compose.worker.command` | the worker runs the durable ingestion loop | — |
| `compose.worker.exact_image_tag` | worker pins an exact image tag | latest is whatever the registry served that morning |
| `compose.worker.healthcheck_disabled` | the worker disables the inherited HTTP healthcheck | an HTTP probe against a loop that serves nothing reports permanent failure |
| `compose.worker.ingestion_mode` | the worker runs in durable asynchronous mode | — |
| `compose.worker.init` | worker runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.worker.network_isolation` | the worker is isolated from the edge network | the worker parses untrusted documents and must not be reachable from outside |
| `compose.worker.no_host_ports` | worker publishes no host ports | a published port is reachable from wherever the host is |
| `compose.worker.no_new_privileges` | worker sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.worker.present` | the worker service is defined | — |
| `compose.worker.resource_ceiling` | worker declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.worker.unprivileged` | worker does not run privileged | a privileged container is the host |

## gitlab-ci

| id | вимога | чому |
|---|---|---|
| `ci.forbidden.docker` | no job uses docker:dind | docker-in-docker and privileged mode both hand the host to the job |
| `ci.forbidden.privileged` | no job uses privileged: true | docker-in-docker and privileged mode both hand the host to the job |
| `ci.gate.gitleaks` | the pipeline runs gitleaks | — |
| `ci.gate.syft` | the pipeline runs syft | — |
| `ci.gate.trivy` | the pipeline runs trivy | — |
| `ci.gate.verify_postgres_restore` | the pipeline runs verify_postgres_restore.py | — |
| `ci.image_built_unprivileged` | the container image is built by a job that needs no privileged capabilities | buildkit needs a nested mount namespace, which on a plain docker executor requires SYS_ADMIN — privileged escape under a different flag name. The requirement is that the image is built unprivileged, not which tool does it |
| `ci.no_global_cache` | the assurance pipeline declares no global cache | a cache carries state between runs, and evidence must come from the tree |
| `ci.postgres_job.database_is_a_service` | the PostgreSQL job attaches the database as a service rather than borrowing its image | an image borrowed for its server binaries brings its interpreter with it |
| `ci.postgres_job.present` | the PostgreSQL job exists | — |

## makefile

| id | вимога | чому |
|---|---|---|
| `make.infra_up_waits` | make infra-up waits for the composed application | returning before the stack is up makes the next command fail for the wrong reason |
| `make.no_phantom_compose_profile` | the Makefile references no nonexistent Compose profile | — |

## minio-policy

| id | вимога | чому |
|---|---|---|
| `minio.policy.durability.GetBucketVersioning` | the application policy can verify s3:GetBucketVersioning | durability the service cannot observe is durability nobody checks |
| `minio.policy.durability.GetObjectLockConfiguration` | the application policy can verify s3:GetObjectLockConfiguration | durability the service cannot observe is durability nobody checks |
| `minio.policy.no_destructive_actions` | the application policy grants no delete or wildcard object access | evidence that can be deleted by the service is not evidence |
| `minio.policy.no_unexpected_prefix` | the application policy grants no object prefix beyond objects and quarantine | — |
| `minio.policy.prefix.objects` | the application policy covers arn:aws:s3:::korpus/objects/* | — |
| `minio.policy.prefix.quarantine` | the application policy covers arn:aws:s3:::korpus/quarantine/* | — |

## packaging

| id | вимога | чому |
|---|---|---|
| `packaging.from_committed_tree` | the release archive originates from the committed Git tree | packaging a working directory ships whatever happened to be lying in it |
| `packaging.rejects_stale_evidence` | packaging refuses stale assurance evidence | — |
| `packaging.replaces_reports` | packaging replaces committed reports instead of nesting stale evidence | — |
