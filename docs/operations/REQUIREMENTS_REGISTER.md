# Реєстр вимог КОРПУСу

Згенеровано `scripts/export_requirements.py`. Не редагувати вручну — джерело це `korpus/infrastructure_requirements.py`, `korpus/repository_requirements.py`, `korpus/kubernetes_requirements.py` та `korpus/controlled_requirements.py`.

Вимоги з префіксом `k8s.` побудовані з `deploy/kubernetes/base`: покомпонентні правила породжуються з набору документів, тому перелік описує саме це розгортання, а не Kubernetes узагалі.

Усього вимог: **323**.

Кожна має ідентифікатор, за яким її можна процитувати в аудиті, позначити як прийнятий ризик із названим власником, зіставити з мутантом і порахувати. До 05.08.2026 їх не було: перевірка існувала як рядок, дописаний у місці збою.

## ConfigMap

| id | вимога | чому |
|---|---|---|
| `k8s.config.korpus_answer_policy_mode` | the deployed configuration carries KORPUS_ANSWER_POLICY_MODE=calibrated | the deployed configuration is what runs; a controlled environment that ships dev auth or automatic schema creation is not the one that was reviewed |
| `k8s.config.korpus_auth_mode` | the deployed configuration carries KORPUS_AUTH_MODE=oidc | the deployed configuration is what runs; a controlled environment that ships dev auth or automatic schema creation is not the one that was reviewed |
| `k8s.config.korpus_browser_auth_enabled` | the deployed configuration carries KORPUS_BROWSER_AUTH_ENABLED=true | the deployed configuration is what runs; a controlled environment that ships dev auth or automatic schema creation is not the one that was reviewed |
| `k8s.config.korpus_corpus_governance_profile_path` | the deployed configuration carries KORPUS_CORPUS_GOVERNANCE_PROFILE_PATH=/etc/korpus/governance/corpus-governance.json | the deployed configuration is what runs; a controlled environment that ships dev auth or automatic schema creation is not the one that was reviewed |
| `k8s.config.korpus_entitlement_profile_path` | the deployed configuration carries KORPUS_ENTITLEMENT_PROFILE_PATH=/etc/korpus/governance/entitlements.json | the deployed configuration is what runs; a controlled environment that ships dev auth or automatic schema creation is not the one that was reviewed |
| `k8s.config.korpus_environment` | the deployed configuration carries KORPUS_ENVIRONMENT=production | the deployed configuration is what runs; a controlled environment that ships dev auth or automatic schema creation is not the one that was reviewed |
| `k8s.config.korpus_ingestion_mode` | the deployed configuration carries KORPUS_INGESTION_MODE=durable_async | the deployed configuration is what runs; a controlled environment that ships dev auth or automatic schema creation is not the one that was reviewed |
| `k8s.config.korpus_require_source_signatures` | the deployed configuration carries KORPUS_REQUIRE_SOURCE_SIGNATURES=true | the deployed configuration is what runs; a controlled environment that ships dev auth or automatic schema creation is not the one that was reviewed |
| `k8s.config.korpus_reviewer_registry_path` | the deployed configuration carries KORPUS_REVIEWER_REGISTRY_PATH=/etc/korpus/governance/reviewers.json | the deployed configuration is what runs; a controlled environment that ships dev auth or automatic schema creation is not the one that was reviewed |
| `k8s.config.korpus_schema_mode` | the deployed configuration carries KORPUS_SCHEMA_MODE=migrations | the deployed configuration is what runs; a controlled environment that ships dev auth or automatic schema creation is not the one that was reviewed |
| `k8s.config.korpus_source_trust_profile_path` | the deployed configuration carries KORPUS_SOURCE_TRUST_PROFILE_PATH=/etc/korpus/governance/source-trust.json | the deployed configuration is what runs; a controlled environment that ships dev auth or automatic schema creation is not the one that was reviewed |

## Namespace

| id | вимога | чому |
|---|---|---|
| `k8s.namespace.restricted_pod_security` | the namespace enforces restricted Pod Security | the namespace label is what a cluster enforces when a workload's own security context is wrong; without it every per-container check here is the only line of defence |

## NetworkPolicy

| id | вимога | чому |
|---|---|---|
| `k8s.network.default_deny` | a default-deny NetworkPolicy with an empty podSelector exists | without an empty podSelector denying everything first, every later policy is an addition to an open network rather than an exception to a closed one |

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

## deployment

| id | вимога | чому |
|---|---|---|
| `k8s.cluster.required_kinds` | every required resource kind is rendered: ['ConfigMap', 'Deployment', 'HorizontalPodAutoscaler', 'Job', 'Namespace', 'NetworkPolicy', 'PodDisruptionBudget', 'Service', 'ServiceAccount'] | a deployment without a NetworkPolicy or a Namespace is not one |
| `k8s.cluster.required_workloads` | every required workload is rendered: ['korpus-api', 'korpus-web', 'korpus-worker'] | a rendered set missing a workload deploys a system with a piece of itself absent, and nothing at runtime reports the absence |

## docker-compose

| id | вимога | чому |
|---|---|---|
| `compose.api.credential.minio_app_access_key` | the API carries its own minio_app_access_key | — |
| `compose.api.credential.minio_app_secret_key` | the API carries its own minio_app_secret_key | — |
| `compose.api.depends_on.clamav` | the API waits for clamav | — |
| `compose.api.depends_on.migrate` | the API waits for migrate | — |
| `compose.api.depends_on.minio-init` | the API waits for minio-init | — |
| `compose.api.depends_on.otel-collector` | the API waits for otel-collector | — |
| `compose.api.digest_pinned` | api pins its image by digest | a tag is a name the registry may repoint; a digest is the bytes. SUP-001, and the reason a version number invented on 2026-08-05 reached a pipeline before anything noticed |
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
| `compose.clamav.digest_pinned` | clamav pins its image by digest | a tag is a name the registry may repoint; a digest is the bytes. SUP-001, and the reason a version number invented on 2026-08-05 reached a pipeline before anything noticed |
| `compose.clamav.exact_image_tag` | clamav pins an exact image tag | latest is whatever the registry served that morning |
| `compose.clamav.init` | clamav runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.clamav.no_host_ports` | clamav publishes no host ports | a published port is reachable from wherever the host is |
| `compose.clamav.no_new_privileges` | clamav sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.clamav.present` | the clamav service is defined | — |
| `compose.clamav.resource_ceiling` | clamav declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.clamav.unprivileged` | clamav does not run privileged | a privileged container is the host |
| `compose.migrate.digest_pinned` | migrate pins its image by digest | a tag is a name the registry may repoint; a digest is the bytes. SUP-001, and the reason a version number invented on 2026-08-05 reached a pipeline before anything noticed |
| `compose.migrate.exact_image_tag` | migrate pins an exact image tag | latest is whatever the registry served that morning |
| `compose.migrate.init` | migrate runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.migrate.no_host_ports` | migrate publishes no host ports | a published port is reachable from wherever the host is |
| `compose.migrate.no_new_privileges` | migrate sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.migrate.present` | the migrate service is defined | — |
| `compose.migrate.resource_ceiling` | migrate declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.migrate.unprivileged` | migrate does not run privileged | a privileged container is the host |
| `compose.minio-init.digest_pinned` | minio-init pins its image by digest | a tag is a name the registry may repoint; a digest is the bytes. SUP-001, and the reason a version number invented on 2026-08-05 reached a pipeline before anything noticed |
| `compose.minio-init.exact_image_tag` | minio-init pins an exact image tag | latest is whatever the registry served that morning |
| `compose.minio-init.init` | minio-init runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.minio-init.no_host_ports` | minio-init publishes no host ports | a published port is reachable from wherever the host is |
| `compose.minio-init.no_new_privileges` | minio-init sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.minio-init.present` | the minio-init service is defined | — |
| `compose.minio-init.resource_ceiling` | minio-init declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.minio-init.unprivileged` | minio-init does not run privileged | a privileged container is the host |
| `compose.minio.digest_pinned` | minio pins its image by digest | a tag is a name the registry may repoint; a digest is the bytes. SUP-001, and the reason a version number invented on 2026-08-05 reached a pipeline before anything noticed |
| `compose.minio.exact_image_tag` | minio pins an exact image tag | latest is whatever the registry served that morning |
| `compose.minio.init` | minio runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.minio.no_host_ports` | minio publishes no host ports | a published port is reachable from wherever the host is |
| `compose.minio.no_new_privileges` | minio sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.minio.present` | the minio service is defined | — |
| `compose.minio.resource_ceiling` | minio declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.minio.unprivileged` | minio does not run privileged | a privileged container is the host |
| `compose.network.backend.internal` | the backend network is internal | an external bridge exposes every service on it to the host network |
| `compose.network.edge.internal` | the edge network is internal | an external bridge exposes every service on it to the host network |
| `compose.otel-collector.digest_pinned` | otel-collector pins its image by digest | a tag is a name the registry may repoint; a digest is the bytes. SUP-001, and the reason a version number invented on 2026-08-05 reached a pipeline before anything noticed |
| `compose.otel-collector.exact_image_tag` | otel-collector pins an exact image tag | latest is whatever the registry served that morning |
| `compose.otel-collector.init` | otel-collector runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.otel-collector.no_host_ports` | otel-collector publishes no host ports | a published port is reachable from wherever the host is |
| `compose.otel-collector.no_new_privileges` | otel-collector sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.otel-collector.present` | the otel-collector service is defined | — |
| `compose.otel-collector.resource_ceiling` | otel-collector declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.otel-collector.unprivileged` | otel-collector does not run privileged | a privileged container is the host |
| `compose.postgres.capabilities` | postgres adds no Linux capability beyond the documented set | — |
| `compose.postgres.digest_pinned` | postgres pins its image by digest | a tag is a name the registry may repoint; a digest is the bytes. SUP-001, and the reason a version number invented on 2026-08-05 reached a pipeline before anything noticed |
| `compose.postgres.exact_image_tag` | postgres pins an exact image tag | latest is whatever the registry served that morning |
| `compose.postgres.init` | postgres runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.postgres.no_host_ports` | postgres publishes no host ports | a published port is reachable from wherever the host is |
| `compose.postgres.no_new_privileges` | postgres sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.postgres.present` | the postgres service is defined | — |
| `compose.postgres.resource_ceiling` | postgres declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.postgres.unprivileged` | postgres does not run privileged | a privileged container is the host |
| `compose.web.digest_pinned` | web pins its image by digest | a tag is a name the registry may repoint; a digest is the bytes. SUP-001, and the reason a version number invented on 2026-08-05 reached a pipeline before anything noticed |
| `compose.web.exact_image_tag` | web pins an exact image tag | latest is whatever the registry served that morning |
| `compose.web.host_reachable` | web is on a non-internal network so its published port is reachable from the host | an internal-only network has no gateway, so a published port never reaches the host |
| `compose.web.init` | web runs under an init process unless it is a one-shot | no init means zombie processes and signals that never arrive |
| `compose.web.no_data_plane` | web touches neither the data plane nor egress | a static server with a route to postgres or the internet is more surface than it needs |
| `compose.web.no_host_ports` | web publishes only on loopback | a published port is reachable from wherever the host is |
| `compose.web.no_new_privileges` | web sets no-new-privileges | without it a setuid binary inside the image escalates |
| `compose.web.present` | the web service is defined | — |
| `compose.web.reaches_api_over_edge` | web is on the internal edge network so it can proxy to api | — |
| `compose.web.resource_ceiling` | web declares memory and CPU ceilings | one unbounded service takes the host down with it |
| `compose.web.unprivileged` | web does not run privileged | a privileged container is the host |
| `compose.worker.clamav` | the worker waits for ClamAV | — |
| `compose.worker.command` | the worker runs the durable ingestion loop | — |
| `compose.worker.digest_pinned` | worker pins its image by digest | a tag is a name the registry may repoint; a digest is the bytes. SUP-001, and the reason a version number invented on 2026-08-05 reached a pipeline before anything noticed |
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
| `ci.images_digest_pinned` | every CI image is pinned by digest | a tag can be repointed; the pipeline's claim is reproducibility |
| `ci.no_global_cache` | the assurance pipeline declares no global cache | a cache carries state between runs, and evidence must come from the tree |
| `ci.postgres_job.database_is_a_service` | the PostgreSQL job attaches the database as a service rather than borrowing its image | an image borrowed for its server binaries brings its interpreter with it |
| `ci.postgres_job.present` | the PostgreSQL job exists | — |

## korpus-api

| id | вимога | чому |
|---|---|---|
| `k8s.workload.korpus-api.container.0.all_capabilities_dropped` | korpus-api: the container drops every capability | dropping a named subset leaves the rest; the destruction stage on 2026-08-03 got past this with `drop: [NET_RAW]` |
| `k8s.workload.korpus-api.container.0.image_digest` | korpus-api: the container image is pinned by digest | a tag is a name the registry may repoint at any time; a digest is the bytes. An overlay patching in `:latest` passed this gate until 2026-08-04, because overlays were never rendered |
| `k8s.workload.korpus-api.container.0.no_privilege_escalation` | korpus-api: the container cannot escalate privilege | setuid inside the container defeats the non-root pod context |
| `k8s.workload.korpus-api.container.0.read_only_root` | korpus-api: the container root filesystem is read-only | a writable root is where an uploaded document becomes an executable |
| `k8s.workload.korpus-api.container.0.resource_bounds` | korpus-api: the container declares resource requests and limits | an unbounded container is the cheapest denial of service in the cluster, available to whoever uploads the largest document |
| `k8s.workload.korpus-api.governance_read_only` | korpus-api: the governance bundle is mounted read-only at its expected path | a writable entitlement profile is an entitlement profile the process that reads it can also edit |
| `k8s.workload.korpus-api.governance_volume` | korpus-api: the governance bundle is supplied as a named secret volume | the governance bundle carries the entitlement profile and its digest; a workload without it falls back to whatever is on disk |
| `k8s.workload.korpus-api.has_containers` | korpus-api: the pod declares at least one container | a workload with no containers passes every per-container check below vacuously, which is the shape of a hardening step that was deleted |
| `k8s.workload.korpus-api.no_service_account_token` | korpus-api: the service-account token is not mounted | a mounted token is a cluster credential inside a process that parses untrusted documents |
| `k8s.workload.korpus-api.restricted_pod_security` | korpus-api: the pod runs non-root under the RuntimeDefault seccomp profile | runAsNonRoot and RuntimeDefault seccomp are the pod-level floor |

## korpus-migrate

| id | вимога | чому |
|---|---|---|
| `k8s.workload.korpus-migrate.container.0.all_capabilities_dropped` | korpus-migrate: the container drops every capability | dropping a named subset leaves the rest; the destruction stage on 2026-08-03 got past this with `drop: [NET_RAW]` |
| `k8s.workload.korpus-migrate.container.0.image_digest` | korpus-migrate: the container image is pinned by digest | a tag is a name the registry may repoint at any time; a digest is the bytes. An overlay patching in `:latest` passed this gate until 2026-08-04, because overlays were never rendered |
| `k8s.workload.korpus-migrate.container.0.no_privilege_escalation` | korpus-migrate: the container cannot escalate privilege | setuid inside the container defeats the non-root pod context |
| `k8s.workload.korpus-migrate.container.0.read_only_root` | korpus-migrate: the container root filesystem is read-only | a writable root is where an uploaded document becomes an executable |
| `k8s.workload.korpus-migrate.container.0.resource_bounds` | korpus-migrate: the container declares resource requests and limits | an unbounded container is the cheapest denial of service in the cluster, available to whoever uploads the largest document |
| `k8s.workload.korpus-migrate.has_containers` | korpus-migrate: the pod declares at least one container | a workload with no containers passes every per-container check below vacuously, which is the shape of a hardening step that was deleted |
| `k8s.workload.korpus-migrate.no_service_account_token` | korpus-migrate: the service-account token is not mounted | a mounted token is a cluster credential inside a process that parses untrusted documents |
| `k8s.workload.korpus-migrate.restricted_pod_security` | korpus-migrate: the pod runs non-root under the RuntimeDefault seccomp profile | runAsNonRoot and RuntimeDefault seccomp are the pod-level floor |

## korpus-web

| id | вимога | чому |
|---|---|---|
| `k8s.workload.korpus-web.container.0.all_capabilities_dropped` | korpus-web: the container drops every capability | dropping a named subset leaves the rest; the destruction stage on 2026-08-03 got past this with `drop: [NET_RAW]` |
| `k8s.workload.korpus-web.container.0.image_digest` | korpus-web: the container image is pinned by digest | a tag is a name the registry may repoint at any time; a digest is the bytes. An overlay patching in `:latest` passed this gate until 2026-08-04, because overlays were never rendered |
| `k8s.workload.korpus-web.container.0.no_privilege_escalation` | korpus-web: the container cannot escalate privilege | setuid inside the container defeats the non-root pod context |
| `k8s.workload.korpus-web.container.0.read_only_root` | korpus-web: the container root filesystem is read-only | a writable root is where an uploaded document becomes an executable |
| `k8s.workload.korpus-web.container.0.resource_bounds` | korpus-web: the container declares resource requests and limits | an unbounded container is the cheapest denial of service in the cluster, available to whoever uploads the largest document |
| `k8s.workload.korpus-web.has_containers` | korpus-web: the pod declares at least one container | a workload with no containers passes every per-container check below vacuously, which is the shape of a hardening step that was deleted |
| `k8s.workload.korpus-web.no_service_account_token` | korpus-web: the service-account token is not mounted | a mounted token is a cluster credential inside a process that parses untrusted documents |
| `k8s.workload.korpus-web.restricted_pod_security` | korpus-web: the pod runs non-root under the RuntimeDefault seccomp profile | runAsNonRoot and RuntimeDefault seccomp are the pod-level floor |

## korpus-worker

| id | вимога | чому |
|---|---|---|
| `k8s.workload.korpus-worker.container.0.all_capabilities_dropped` | korpus-worker: the container drops every capability | dropping a named subset leaves the rest; the destruction stage on 2026-08-03 got past this with `drop: [NET_RAW]` |
| `k8s.workload.korpus-worker.container.0.image_digest` | korpus-worker: the container image is pinned by digest | a tag is a name the registry may repoint at any time; a digest is the bytes. An overlay patching in `:latest` passed this gate until 2026-08-04, because overlays were never rendered |
| `k8s.workload.korpus-worker.container.0.no_privilege_escalation` | korpus-worker: the container cannot escalate privilege | setuid inside the container defeats the non-root pod context |
| `k8s.workload.korpus-worker.container.0.read_only_root` | korpus-worker: the container root filesystem is read-only | a writable root is where an uploaded document becomes an executable |
| `k8s.workload.korpus-worker.container.0.resource_bounds` | korpus-worker: the container declares resource requests and limits | an unbounded container is the cheapest denial of service in the cluster, available to whoever uploads the largest document |
| `k8s.workload.korpus-worker.governance_read_only` | korpus-worker: the governance bundle is mounted read-only at its expected path | a writable entitlement profile is an entitlement profile the process that reads it can also edit |
| `k8s.workload.korpus-worker.governance_volume` | korpus-worker: the governance bundle is supplied as a named secret volume | the governance bundle carries the entitlement profile and its digest; a workload without it falls back to whatever is on disk |
| `k8s.workload.korpus-worker.has_containers` | korpus-worker: the pod declares at least one container | a workload with no containers passes every per-container check below vacuously, which is the shape of a hardening step that was deleted |
| `k8s.workload.korpus-worker.no_service_account_token` | korpus-worker: the service-account token is not mounted | a mounted token is a cluster credential inside a process that parses untrusted documents |
| `k8s.workload.korpus-worker.restricted_pod_security` | korpus-worker: the pod runs non-root under the RuntimeDefault seccomp profile | runAsNonRoot and RuntimeDefault seccomp are the pod-level floor |

## makefile

| id | вимога | чому |
|---|---|---|
| `make.infra_up_waits` | make infra-up waits for the composed application | returning before the stack is up makes the next command fail for the wrong reason |
| `make.no_phantom_compose_profile` | the Makefile references no nonexistent Compose profile | — |

## minio-policy

| id | вимога | чому |
|---|---|---|
| `minio.policy.durability.GetBucketObjectLockConfiguration` | the application policy can verify s3:GetBucketObjectLockConfiguration | durability the service cannot observe is durability nobody checks |
| `minio.policy.durability.GetBucketVersioning` | the application policy can verify s3:GetBucketVersioning | durability the service cannot observe is durability nobody checks |
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

## repository

| id | вимога | чому |
|---|---|---|
| `repo.closure.classifies_every_finding` | the audit closure classifies exactly 99 source findings | a finding dropped from the register is a finding nobody has to answer for |
| `repo.closure.counts_sum` | the closure status counts sum to 99 | counts that do not sum mean a finding is in two states or none |
| `repo.closure.target_release` | the audit closure targets v5.0.0 | — |
| `repo.file.agents_md` | AGENTS.md is present | — |
| `repo.file.apps_api_pyproject_toml` | apps/api/pyproject.toml is present | — |
| `repo.file.apps_api_requirements_dev_lock` | apps/api/requirements.dev.lock is present | — |
| `repo.file.apps_api_requirements_runtime_lock` | apps/api/requirements.runtime.lock is present | — |
| `repo.file.apps_api_src_korpus_infrastructure_ingestion_jobs_py` | apps/api/src/korpus/infrastructure/ingestion_jobs.py is present | — |
| `repo.file.apps_api_src_korpus_infrastructure_parser_worker_py` | apps/api/src/korpus/infrastructure/parser_worker.py is present | — |
| `repo.file.apps_api_src_korpus_main_py` | apps/api/src/korpus/main.py is present | — |
| `repo.file.apps_api_src_korpus_release_json` | apps/api/src/korpus/release.json is present | — |
| `repo.file.apps_api_src_korpus_security_browser_oidc_py` | apps/api/src/korpus/security/browser_oidc.py is present | — |
| `repo.file.apps_api_src_korpus_security_corpus_governance_py` | apps/api/src/korpus/security/corpus_governance.py is present | — |
| `repo.file.apps_api_src_korpus_security_entitlements_py` | apps/api/src/korpus/security/entitlements.py is present | — |
| `repo.file.apps_api_src_korpus_security_reviewers_py` | apps/api/src/korpus/security/reviewers.py is present | — |
| `repo.file.apps_api_src_korpus_security_scanning_py` | apps/api/src/korpus/security/scanning.py is present | — |
| `repo.file.apps_api_src_korpus_security_source_authenticity_py` | apps/api/src/korpus/security/source_authenticity.py is present | — |
| `repo.file.apps_web_package_json` | apps/web/package.json is present | — |
| `repo.file.config_operations_desired_state_json` | config/operations/desired-state.json is present | — |
| `repo.file.config_operations_reference_v5_json` | config/operations/reference-v5.json is present | — |
| `repo.file.contracts_openapi_json` | contracts/openapi.json is present | — |
| `repo.file.deploy_kubernetes_base_kustomization_yaml` | deploy/kubernetes/base/kustomization.yaml is present | — |
| `repo.file.deploy_kubernetes_overlays_production_kustomization_yaml` | deploy/kubernetes/overlays/production/kustomization.yaml is present | — |
| `repo.file.distribution_contents_md` | DISTRIBUTION_CONTENTS.md is present | — |
| `repo.file.docker_compose_yml` | docker-compose.yml is present | — |
| `repo.file.dockerignore` | .dockerignore is present | — |
| `repo.file.docs_architecture_security_md` | docs/architecture/SECURITY.md is present | — |
| `repo.file.docs_architecture_system_md` | docs/architecture/SYSTEM.md is present | — |
| `repo.file.docs_assurance_assurance_case_md` | docs/assurance/ASSURANCE_CASE.md is present | — |
| `repo.file.docs_assurance_first_principles_md` | docs/assurance/FIRST_PRINCIPLES.md is present | — |
| `repo.file.docs_assurance_test_strategy_md` | docs/assurance/TEST_STRATEGY.md is present | — |
| `repo.file.docs_audit_closure_korpus_v5_closure_summary_md` | docs/audit/closure/KORPUS_v5_CLOSURE_SUMMARY.md is present | — |
| `repo.file.docs_audit_closure_korpus_v5_findings_closure_csv` | docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.csv is present | — |
| `repo.file.docs_audit_closure_korpus_v5_findings_closure_json` | docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json is present | — |
| `repo.file.docs_audit_closure_korpus_v5_remaining_debt_csv` | docs/audit/closure/KORPUS_v5_REMAINING_DEBT.csv is present | — |
| `repo.file.docs_audit_closure_korpus_v5_remaining_debt_json` | docs/audit/closure/KORPUS_v5_REMAINING_DEBT.json is present | — |
| `repo.file.docs_audit_source_korpus_v4_extended_assurance_act_2026_08_01_docx` | docs/audit/source/KORPUS_v4_EXTENDED_ASSURANCE_ACT_2026-08-01.docx is present | — |
| `repo.file.docs_audit_source_korpus_v4_extended_assurance_act_2026_08_01_md` | docs/audit/source/KORPUS_v4_EXTENDED_ASSURANCE_ACT_2026-08-01.md is present | — |
| `repo.file.docs_audit_source_korpus_v4_extended_assurance_act_2026_08_01_pdf` | docs/audit/source/KORPUS_v4_EXTENDED_ASSURANCE_ACT_2026-08-01.pdf is present | — |
| `repo.file.docs_audit_source_korpus_v4_extended_audit_package_2026_08_01_zip` | docs/audit/source/KORPUS_v4_EXTENDED_AUDIT_PACKAGE_2026-08-01.zip is present | — |
| `repo.file.docs_audit_source_korpus_v4_findings_register_2026_08_01_json` | docs/audit/source/KORPUS_v4_FINDINGS_REGISTER_2026-08-01.json is present | — |
| `repo.file.docs_governance_ai_system_card_v5_md` | docs/governance/AI_SYSTEM_CARD_V5.md is present | — |
| `repo.file.docs_governance_authorization_package_v5_md` | docs/governance/AUTHORIZATION_PACKAGE_V5.md is present | — |
| `repo.file.docs_governance_data_handling_standard_v5_md` | docs/governance/DATA_HANDLING_STANDARD_V5.md is present | — |
| `repo.file.docs_operations_slo_and_release_policy_v5_md` | docs/operations/SLO_AND_RELEASE_POLICY_V5.md is present | — |
| `repo.file.docs_operations_technical_debt_v5_md` | docs/operations/TECHNICAL_DEBT_V5.md is present | — |
| `repo.file.docs_operations_tevv_plan_v5_md` | docs/operations/TEVV_PLAN_V5.md is present | — |
| `repo.file.docs_security_key_and_break_glass_v5_md` | docs/security/KEY_AND_BREAK_GLASS_V5.md is present | — |
| `repo.file.docs_security_threat_model_v5_md` | docs/security/THREAT_MODEL_V5.md is present | — |
| `repo.file.evals_datasets_frozen_jsonl` | evals/datasets/frozen.jsonl is present | — |
| `repo.file.evals_evaluation_protocol_md` | evals/EVALUATION_PROTOCOL.md is present | — |
| `repo.file.final_package_contents_md` | FINAL_PACKAGE_CONTENTS.md is present | — |
| `repo.file.gitlab_ci_yml` | .gitlab-ci.yml is present | — |
| `repo.file.gitlab_codeowners` | .gitlab/CODEOWNERS is present | — |
| `repo.file.gitlab_import_md` | GITLAB_IMPORT.md is present | — |
| `repo.file.infra_minio_korpus_app_policy_json` | infra/minio/korpus-app-policy.json is present | — |
| `repo.file.packages_contracts_answer_schema_json` | packages/contracts/answer.schema.json is present | — |
| `repo.file.pytest_ini` | pytest.ini is present | — |
| `repo.file.readme_md` | README.md is present | — |
| `repo.file.scripts_assemble_assurance_py` | scripts/assemble_assurance.py is present | — |
| `repo.file.scripts_backup_crypto_py` | scripts/backup_crypto.py is present | — |
| `repo.file.scripts_backup_manifest_py` | scripts/backup_manifest.py is present | — |
| `repo.file.scripts_backup_postgres_sh` | scripts/backup_postgres.sh is present | — |
| `repo.file.scripts_build_audit_closure_py` | scripts/build_audit_closure.py is present | — |
| `repo.file.scripts_build_system_manifest_py` | scripts/build_system_manifest.py is present | — |
| `repo.file.scripts_generate_desired_state_py` | scripts/generate_desired_state.py is present | — |
| `repo.file.scripts_generate_supply_chain_inventory_py` | scripts/generate_supply_chain_inventory.py is present | — |
| `repo.file.scripts_openapi_contract_py` | scripts/openapi_contract.py is present | — |
| `repo.file.scripts_package_repository_sh` | scripts/package_repository.sh is present | — |
| `repo.file.scripts_restore_postgres_sh` | scripts/restore_postgres.sh is present | — |
| `repo.file.scripts_run_evals_py` | scripts/run_evals.py is present | — |
| `repo.file.scripts_run_migration_gate_py` | scripts/run_migration_gate.py is present | — |
| `repo.file.scripts_run_mutation_shards_sh` | scripts/run_mutation_shards.sh is present | — |
| `repo.file.scripts_run_mutation_tests_py` | scripts/run_mutation_tests.py is present | — |
| `repo.file.scripts_run_operational_gate_py` | scripts/run_operational_gate.py is present | — |
| `repo.file.scripts_run_research_assurance_py` | scripts/run_research_assurance.py is present | — |
| `repo.file.scripts_run_scale_probe_py` | scripts/run_scale_probe.py is present | — |
| `repo.file.scripts_snapshot_assurance_py` | scripts/snapshot_assurance.py is present | — |
| `repo.file.scripts_source_digest_py` | scripts/source_digest.py is present | — |
| `repo.file.scripts_validate_infrastructure_py` | scripts/validate_infrastructure.py is present | — |
| `repo.file.scripts_validate_kubernetes_py` | scripts/validate_kubernetes.py is present | — |
| `repo.file.scripts_verify_postgres_restore_py` | scripts/verify_postgres_restore.py is present | — |
| `repo.file.scripts_verify_release_evidence_py` | scripts/verify_release_evidence.py is present | — |
| `repo.file.security_md` | SECURITY.md is present | — |
| `repo.file.verification_report_md` | VERIFICATION_REPORT.md is present | — |
| `repo.json_documents_parse` | every shipped JSON contract and schema parses | a contract that does not parse is a contract nothing enforces |
| `repo.migration.0001_initial_py` | migration 0001_initial.py is present | a migration missing from the tree is a schema step nobody can apply or review |
| `repo.migration.0002_database_defense_and_vectors_py` | migration 0002_database_defense_and_vectors.py is present | a migration missing from the tree is a schema step nobody can apply or review |
| `repo.migration.0003_infrastructure_hardening_py` | migration 0003_infrastructure_hardening.py is present | a migration missing from the tree is a schema step nobody can apply or review |
| `repo.migration.0004_compartmented_authorization_py` | migration 0004_compartmented_authorization.py is present | a migration missing from the tree is a schema step nobody can apply or review |
| `repo.migration.0005_durable_ingestion_jobs_py` | migration 0005_durable_ingestion_jobs.py is present | a migration missing from the tree is a schema step nobody can apply or review |
| `repo.migration.0006_source_authenticity_py` | migration 0006_source_authenticity.py is present | a migration missing from the tree is a schema step nobody can apply or review |
| `repo.migration.0007_near_duplicate_governance_py` | migration 0007_near_duplicate_governance.py is present | a migration missing from the tree is a schema step nobody can apply or review |
| `repo.migration.0008_extraction_quality_governance_py` | migration 0008_extraction_quality_governance.py is present | a migration missing from the tree is a schema step nobody can apply or review |
| `repo.migration.0009_reviewer_credentials_py` | migration 0009_reviewer_credentials.py is present | a migration missing from the tree is a schema step nobody can apply or review |
| `repo.no_oversized_files` | no tracked file exceeds 5 MB | a large binary in the tree is a thing nobody reviews and everybody clones |
| `repo.no_plaintext_secrets` | no plaintext runtime secret is tracked | a secret in the tree is disclosed to everyone who ever clones it, forever |
| `repo.no_unresolved_placeholders` | no shipped source carries an unresolved implementation placeholder | NotImplementedError in a delivered path is a promise the runtime cannot keep |
| `repo.version.api_pyproject` | api_pyproject declares release 6.8.1 | release identity and its derivative surfaces must agree; one mismatch means the artefacts describe different builds |
| `repo.version.readme_header` | readme_header declares release 6.8.1 | release identity and its derivative surfaces must agree; one mismatch means the artefacts describe different builds |
| `repo.version.release_identity` | release_identity declares release 6.8.1 | release identity and its derivative surfaces must agree; one mismatch means the artefacts describe different builds |
| `repo.version.runtime_dunder` | runtime_dunder declares release 6.8.1 | release identity and its derivative surfaces must agree; one mismatch means the artefacts describe different builds |
| `repo.version.web_package` | web_package declares release 6.8.1 | release identity and its derivative surfaces must agree; one mismatch means the artefacts describe different builds |
