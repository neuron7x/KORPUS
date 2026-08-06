"""What the deployment substrate must be true of, as a register rather than a routine.

Every entry here was a line inside `validate_infrastructure.main`, which reached a
cyclomatic complexity of 102 as a run of `if …: failures.append("…")`. The behaviour is
unchanged and the messages are preserved verbatim, because `test_infrastructure_
hardening.py` pins them and an unchanged test passing over rearranged code is the only
thing that makes a refactor of a security validator evidence rather than hope.

What changes is that each check now has an id. That is what lets a failure be cited in
an audit, marked accepted-with-risk by a named owner, matched to a mutant, and counted.
A string appended at the point of failure could be none of those.

Grouped by subject, in the order they were checked, so the diff against the original is
readable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from korpus.application.requirements import Requirement

REQUIRED_SERVICES = frozenset(
    {
        "postgres",
        "migrate",
        "minio",
        "minio-init",
        "otel-collector",
        "clamav",
        "api",
        "worker",
        "web",
    }
)
# `name:tag` or `name:tag@sha256:…`. The digest form is what SUP-001 asked for; the
# tag stays beside it because a diff that says only "64 hex characters changed" tells
# a reviewer nothing about which version moved.
EXACT_TAG = re.compile(r"^[^:@\s]+:[^:@\s]+(?:@sha256:[0-9a-f]{64})?$")
DIGEST_PINNED = re.compile(r"@sha256:[0-9a-f]{64}$")
ALLOWED_POSTGRES_CAPABILITIES = frozenset(
    {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"}
)
WORKER_COMMAND = ["python", "-m", "korpus.cli", "worker-loop", "--idle-seconds", "1"]


@dataclass
class InfrastructureContext:
    """Every artefact the register reads, loaded once.

    Loaded eagerly rather than on demand: a requirement whose file is missing must fail
    as a requirement, and a lazy loader would raise inside the first predicate that
    touched it and hide the rest.
    """

    root: Path
    compose: dict[str, Any] = field(default_factory=dict)
    ci_text: str = ""
    package_text: str = ""
    backup_text: str = ""
    restore_text: str = ""
    manifest_text: str = ""
    make_text: str = ""
    dockerignore: str = ""
    api_dockerfile: str = ""
    web_dockerfile: str = ""
    minio_policy: dict[str, Any] = field(default_factory=dict)
    load_errors: list[str] = field(default_factory=list)

    @property
    def services(self) -> dict[str, Any]:
        return self.compose.get("services", {}) or {}

    def service(self, name: str) -> dict[str, Any]:
        return self.services.get(name, {}) or {}

    def environment(self, name: str) -> dict[str, Any]:
        return self.service(name).get("environment", {}) or {}

    @property
    def ci_directives(self) -> list[str]:
        """CI lines that are instructions, not commentary.

        The forbidden-construct check once matched the raw file, so the comment
        explaining why privileged mode is banned tripped the ban on privileged mode.
        """
        return [line for line in self.ci_text.splitlines() if not line.lstrip().startswith("#")]

    def ci_block(self, job: str) -> str:
        return next(
            (
                block
                for block in re.split(r"\n(?=\S)", self.ci_text)
                if block.startswith(f"{job}:")
            ),
            "",
        )

    def minio_actions(self) -> set[str]:
        return {
            action
            for statement in self.minio_policy.get("Statement", [])
            for action in statement.get("Action", [])
        }

    def minio_resources(self) -> set[str]:
        return {
            resource
            for statement in self.minio_policy.get("Statement", [])
            for resource in statement.get("Resource", [])
        }

    def api_secret_text(self) -> str:
        api = self.service("api")
        return json.dumps(api.get("secrets", []), sort_keys=True) + json.dumps(
            self.environment("api"), sort_keys=True
        )


def load_context(root: Path) -> InfrastructureContext:
    import yaml

    context = InfrastructureContext(root=root)

    def read(relative: str) -> str:
        try:
            return (root / relative).read_text(encoding="utf-8")
        except OSError as error:
            context.load_errors.append(f"{relative}: {error}")
            return ""

    try:
        context.compose = yaml.safe_load(read("docker-compose.yml")) or {}
    except yaml.YAMLError as error:
        context.load_errors.append(f"docker-compose.yml: {error}")
    context.ci_text = read(".gitlab-ci.yml")
    context.package_text = read("scripts/package_repository.sh")
    context.backup_text = read("scripts/backup_postgres.sh")
    context.restore_text = read("scripts/restore_postgres.sh")
    context.manifest_text = read("scripts/backup_manifest.py")
    context.make_text = read("Makefile")
    context.dockerignore = read(".dockerignore")
    context.api_dockerfile = read("apps/api/Dockerfile")
    context.web_dockerfile = read("apps/web/Dockerfile")
    try:
        context.minio_policy = json.loads(read("infra/minio/korpus-app-policy.json") or "{}")
    except json.JSONDecodeError as error:
        context.load_errors.append(f"infra/minio/korpus-app-policy.json: {error}")
    return context


def _requirement(
    identifier: str, subject: str, statement: str, holds: Any, rationale: str = ""
) -> Requirement:
    return Requirement(
        id=identifier, subject=subject, statement=statement, holds=holds, rationale=rationale
    )


def _service_requirements() -> list[Requirement]:
    """Per-service properties, expanded over the required service list.

    Generated rather than written out: a service added to REQUIRED_SERVICES without its
    hardening checks is the gap this shape closes.
    """
    checks: list[Requirement] = []
    for name in sorted(REQUIRED_SERVICES):
        checks.extend(
            [
                _requirement(
                    f"compose.{name}.present",
                    "docker-compose",
                    f"the {name} service is defined",
                    lambda c, n=name: n in c.services,
                ),
                _requirement(
                    f"compose.{name}.unprivileged",
                    "docker-compose",
                    f"{name} does not run privileged",
                    lambda c, n=name: not c.service(n).get("privileged"),
                    "a privileged container is the host",
                ),
                _requirement(
                    f"compose.{name}.no_new_privileges",
                    "docker-compose",
                    f"{name} sets no-new-privileges",
                    lambda c, n=name: "no-new-privileges:true"
                    in (c.service(n).get("security_opt", []) or []),
                    "without it a setuid binary inside the image escalates",
                ),
                _requirement(
                    f"compose.{name}.init",
                    "docker-compose",
                    f"{name} runs under an init process unless it is a one-shot",
                    lambda c, n=name: c.service(n).get("restart") == "no"
                    or bool(c.service(n).get("init")),
                    "no init means zombie processes and signals that never arrive",
                ),
                _requirement(
                    f"compose.{name}.resource_ceiling",
                    "docker-compose",
                    f"{name} declares memory and CPU ceilings",
                    lambda c, n=name: bool(c.service(n).get("mem_limit"))
                    and bool(c.service(n).get("cpus")),
                    "one unbounded service takes the host down with it",
                ),
                _requirement(
                    f"compose.{name}.exact_image_tag",
                    "docker-compose",
                    f"{name} pins an exact image tag",
                    lambda c, n=name: not c.service(n).get("image")
                    or (
                        bool(EXACT_TAG.fullmatch(str(c.service(n)["image"])))
                        and not str(c.service(n)["image"]).endswith(":latest")
                    ),
                    "latest is whatever the registry served that morning",
                ),
                _requirement(
                    f"compose.{name}.digest_pinned",
                    "docker-compose",
                    f"{name} pins its image by digest",
                    lambda c, n=name: not c.service(n).get("image")
                    or bool(DIGEST_PINNED.search(str(c.service(n)["image"]))),
                    "a tag is a name the registry may repoint; a digest is the bytes. "
                    "SUP-001, and the reason a version number invented on 2026-08-05 "
                    "reached a pipeline before anything noticed",
                ),
                _requirement(
                    f"compose.{name}.no_host_ports",
                    "docker-compose",
                    f"{name} publishes no host ports"
                    if name != "web"
                    else "web publishes only on loopback",
                    lambda c, n=name: (not c.service(n).get("ports"))
                    if n != "web"
                    else all(
                        str(port).startswith("127.0.0.1:")
                        for port in (c.service(n).get("ports", []) or [])
                    ),
                    "a published port is reachable from wherever the host is",
                ),
            ]
        )
    return checks


INFRASTRUCTURE_REQUIREMENTS: tuple[Requirement, ...] = (
    *_service_requirements(),
    # --- API service -----------------------------------------------------------
    _requirement(
        "compose.api.schema_mode",
        "docker-compose",
        "the API runs migration-managed schema",
        lambda c: str(c.environment("api").get("KORPUS_SCHEMA_MODE", "")).lower()
        == "migrations",
    ),
    _requirement(
        "compose.api.object_store_mode",
        "docker-compose",
        "the API uses S3-compatible object storage",
        lambda c: str(c.environment("api").get("KORPUS_OBJECT_STORE_MODE", "")).lower() == "s3",
    ),
    _requirement(
        "compose.api.s3_path_style",
        "docker-compose",
        "the API addresses S3 by path style",
        lambda c: str(c.environment("api").get("KORPUS_S3_FORCE_PATH_STYLE", "")).lower()
        == "true",
    ),
    _requirement(
        "compose.api.postgres_url",
        "docker-compose",
        "the API connects through the psycopg PostgreSQL driver",
        lambda c: "postgresql+psycopg"
        in str(c.environment("api").get("KORPUS_DATABASE_URL_TEMPLATE", "")),
    ),
    *[
        _requirement(
            f"compose.api.depends_on.{dependency}",
            "docker-compose",
            f"the API waits for {dependency}",
            lambda c, d=dependency: d in (c.service("api").get("depends_on", {}) or {}),
        )
        for dependency in ("migrate", "minio-init", "otel-collector", "clamav")
    ],
    _requirement(
        "compose.api.read_only_root",
        "docker-compose",
        "the API root filesystem is read-only",
        lambda c: bool(c.service("api").get("read_only")),
        "a writable root turns a parser bug into a persistent implant",
    ),
    _requirement(
        "compose.api.ingestion_mode",
        "docker-compose",
        "the API uses durable asynchronous ingestion",
        lambda c: str(c.environment("api").get("KORPUS_INGESTION_MODE", "")).lower()
        == "durable_async",
    ),
    _requirement(
        "compose.api.malware_scan",
        "docker-compose",
        "the API scans uploads through clamd",
        lambda c: str(c.environment("api").get("KORPUS_MALWARE_SCAN_MODE", "")).lower()
        == "clamd",
    ),
    _requirement(
        "compose.api.parser_sandbox",
        "docker-compose",
        "the API isolates the parser in its own process",
        lambda c: str(c.environment("api").get("KORPUS_PARSER_SANDBOX_ENABLED", "")).lower()
        == "true",
        "the parser reads bytes chosen by whoever uploaded them",
    ),
    _requirement(
        "compose.api.no_minio_root",
        "docker-compose",
        "the API never mounts MinIO root credentials",
        lambda c: "minio_root_password" not in c.api_secret_text(),
        "root credentials make every object-storage control advisory",
    ),
    *[
        _requirement(
            f"compose.api.credential.{credential}",
            "docker-compose",
            f"the API carries its own {credential}",
            lambda c, name=credential: name in c.api_secret_text(),
        )
        for credential in ("minio_app_access_key", "minio_app_secret_key")
    ],
    _requirement(
        "compose.api.egress_network",
        "docker-compose",
        "the API has a dedicated egress network",
        lambda c: "egress" in set(c.service("api").get("networks", []) or []),
    ),
    # --- worker ----------------------------------------------------------------
    _requirement(
        "compose.worker.command",
        "docker-compose",
        "the worker runs the durable ingestion loop",
        lambda c: c.service("worker").get("command") == WORKER_COMMAND,
    ),
    _requirement(
        "compose.worker.ingestion_mode",
        "docker-compose",
        "the worker runs in durable asynchronous mode",
        lambda c: str(c.environment("worker").get("KORPUS_INGESTION_MODE", "")).lower()
        == "durable_async",
    ),
    _requirement(
        "compose.worker.network_isolation",
        "docker-compose",
        "the worker is isolated from the edge network",
        lambda c: set(c.service("worker").get("networks", []) or []) == {"backend", "egress"},
        "the worker parses untrusted documents and must not be reachable from outside",
    ),
    _requirement(
        "compose.worker.healthcheck_disabled",
        "docker-compose",
        "the worker disables the inherited HTTP healthcheck",
        lambda c: bool((c.service("worker").get("healthcheck", {}) or {}).get("disable")),
        "an HTTP probe against a loop that serves nothing reports permanent failure",
    ),
    _requirement(
        "compose.worker.clamav",
        "docker-compose",
        "the worker waits for ClamAV",
        lambda c: "clamav" in (c.service("worker").get("depends_on", {}) or {}),
    ),
    # --- object storage policy --------------------------------------------------
    _requirement(
        "minio.policy.no_destructive_actions",
        "minio-policy",
        "the application policy grants no delete or wildcard object access",
        lambda c: "s3:DeleteObject" not in c.minio_actions() and "s3:*" not in c.minio_actions(),
        "evidence that can be deleted by the service is not evidence",
    ),
    *[
        _requirement(
            f"minio.policy.durability.{action.split(':')[-1]}",
            "minio-policy",
            f"the application policy can verify {action}",
            lambda c, a=action: a in c.minio_actions(),
            "durability the service cannot observe is durability nobody checks",
        )
        # `s3:GetBucketObjectLockConfiguration`, not `s3:GetObjectLockConfiguration`.
        # The AWS name was written here from the documentation and never asked of the
        # server it governs: MinIO refuses the policy outright — "unsupported action
        # 's3:GetObjectLockConfiguration'" — so the policy was never applied, the
        # application user never got it, and this requirement passed against a file
        # nobody had ever loaded. Found by running the compose topology on 2026-08-06.
        for action in ("s3:GetBucketVersioning", "s3:GetBucketObjectLockConfiguration")
    ],
    *[
        _requirement(
            f"minio.policy.prefix.{prefix.rsplit('/', 2)[-2]}",
            "minio-policy",
            f"the application policy covers {prefix}",
            lambda c, p=prefix: p in c.minio_resources(),
        )
        for prefix in ("arn:aws:s3:::korpus/objects/*", "arn:aws:s3:::korpus/quarantine/*")
    ],
    _requirement(
        "minio.policy.no_unexpected_prefix",
        "minio-policy",
        "the application policy grants no object prefix beyond objects and quarantine",
        lambda c: not any(
            resource.endswith("/*")
            and resource
            not in {"arn:aws:s3:::korpus/objects/*", "arn:aws:s3:::korpus/quarantine/*"}
            for resource in c.minio_resources()
        ),
    ),
    # --- database ---------------------------------------------------------------
    _requirement(
        "compose.postgres.capabilities",
        "docker-compose",
        "postgres adds no Linux capability beyond the documented set",
        lambda c: not (
            set(c.service("postgres").get("cap_add", []) or []) - ALLOWED_POSTGRES_CAPABILITIES
        ),
    ),
    # --- networks ---------------------------------------------------------------
    _requirement(
        "compose.web.edge_only",
        "docker-compose",
        "web is isolated to the internal edge network",
        lambda c: set(c.service("web").get("networks", []) or []) == {"edge"},
    ),
    *[
        _requirement(
            f"compose.network.{network}.internal",
            "docker-compose",
            f"the {network} network is internal",
            lambda c, n=network: (c.compose.get("networks", {}) or {}).get(n, {}).get("internal")
            is True,
            "an external bridge exposes every service on it to the host network",
        )
        for network in ("edge", "backend")
    ],
    # --- CI ---------------------------------------------------------------------
    _requirement(
        "ci.no_global_cache",
        "gitlab-ci",
        "the assurance pipeline declares no global cache",
        lambda c: "\ncache:\n" not in c.ci_text,
        "a cache carries state between runs, and evidence must come from the tree",
    ),
    *[
        _requirement(
            f"ci.forbidden.{forbidden.split(':')[0].replace('/', '_')}",
            "gitlab-ci",
            f"no job uses {forbidden}",
            lambda c, f=forbidden: not any(f in line for line in c.ci_directives),
            "docker-in-docker and privileged mode both hand the host to the job",
        )
        for forbidden in ("privileged: true", "docker:dind")
    ],
    *[
        _requirement(
            f"ci.gate.{gate.split('/')[-1].split('.')[0]}",
            "gitlab-ci",
            f"the pipeline runs {gate}",
            lambda c, g=gate: g in c.ci_text,
        )
        for gate in ("gitleaks", "trivy", "syft", "verify_postgres_restore.py")
    ],
    _requirement(
        "ci.image_built_unprivileged",
        "gitlab-ci",
        "the container image is built by a job that needs no privileged capabilities",
        lambda c: any(
            builder in c.ci_text for builder in ("kaniko-project/executor", "moby/buildkit")
        ),
        "buildkit needs a nested mount namespace, which on a plain docker executor "
        "requires SYS_ADMIN — privileged escape under a different flag name. The "
        "requirement is that the image is built unprivileged, not which tool does it",
    ),
    _requirement(
        "ci.images_digest_pinned",
        "gitlab-ci",
        "every CI image is pinned by digest",
        lambda c: all(
            "@sha256:" in line
            for line in c.ci_directives
            if re.match(r"^\s*(?:image:|name:)\s*\S+/\S+|^\s*image:\s*\w+:", line)
            and "korpus" not in line
        ),
        "a tag can be repointed; the pipeline's claim is reproducibility",
    ),
    _requirement(
        "ci.postgres_job.present",
        "gitlab-ci",
        "the PostgreSQL job exists",
        lambda c: bool(c.ci_block("api:postgres-and-restore")),
    ),
    _requirement(
        "ci.postgres_job.database_is_a_service",
        "gitlab-ci",
        "the PostgreSQL job attaches the database as a service rather than borrowing its image",
        lambda c: (
            'entrypoint: [""]' in c.ci_block("api:postgres-and-restore")
            if re.search(
                r"^\s+image:\s*\n\s+name:\s*pgvector",
                c.ci_block("api:postgres-and-restore"),
                re.M,
            )
            else bool(
                re.search(
                    r"^\s+services:\s*\n\s+- name:\s*pgvector",
                    c.ci_block("api:postgres-and-restore"),
                    re.M,
                )
            )
        ),
        "an image borrowed for its server binaries brings its interpreter with it",
    ),
    # --- release packaging ------------------------------------------------------
    _requirement(
        "packaging.from_committed_tree",
        "packaging",
        "the release archive originates from the committed Git tree",
        lambda c: "git archive --format=tar HEAD" in c.package_text,
        "packaging a working directory ships whatever happened to be lying in it",
    ),
    _requirement(
        "packaging.rejects_stale_evidence",
        "packaging",
        "packaging refuses stale assurance evidence",
        lambda c: "verify_release_evidence.py" in c.package_text,
    ),
    _requirement(
        "packaging.replaces_reports",
        "packaging",
        "packaging replaces committed reports instead of nesting stale evidence",
        lambda c: 'rm -rf "$tmp/reports"' in c.package_text,
    ),
    # --- backup and restore -----------------------------------------------------
    *[
        _requirement(
            f"backup.{script}.encryption_key_required",
            "backup",
            f"{script}.sh requires the backup encryption key",
            lambda c, s=script: "KORPUS_BACKUP_ENCRYPTION_KEY_FILE"
            in (c.backup_text if s == "backup_postgres" else c.restore_text),
        )
        for script in ("backup_postgres", "restore_postgres")
    ],
    _requirement(
        "backup.manifest.authenticated_schema",
        "backup",
        "the backup manifest carries the current authenticated schema",
        lambda c: "korpus-postgres-backup-v4" in c.manifest_text
        and "manifest_hmac_sha256" in c.manifest_text,
    ),
    _requirement(
        "backup.key_identity_mandatory",
        "backup",
        "backup and restore both require the encryption key identity",
        lambda c: "KORPUS_BACKUP_KEY_ID" in c.backup_text
        and "KORPUS_BACKUP_KEY_ID" in c.restore_text,
        "a backup encrypted under an unknown key cannot be restored deliberately",
    ),
    _requirement(
        "backup.streams_to_stdout",
        "backup",
        "pg_dump streams into encryption without a plaintext file",
        lambda c: "encrypt-stdin" in c.backup_text,
        "a plaintext dump on disk is the corpus, unencrypted, for as long as it exists",
    ),
    _requirement(
        "backup.no_file_flag",
        "backup",
        "pg_dump is never given --file",
        lambda c: "--file="
        not in "\n".join(
            line for line in c.backup_text.splitlines() if not line.lstrip().startswith("#")
        ),
        "on PostgreSQL 17 --file=- wrote a file named '-' and encrypted nothing",
    ),
    _requirement(
        "backup.manifest_verified_on_both_sides",
        "backup",
        "backup and restore both verify the authenticated manifest",
        lambda c: "backup_manifest.py" in c.backup_text
        and "backup_manifest.py" in c.restore_text,
    ),
    # --- developer entry points --------------------------------------------------
    _requirement(
        "make.no_phantom_compose_profile",
        "makefile",
        "the Makefile references no nonexistent Compose profile",
        lambda c: "--profile support" not in c.make_text,
    ),
    _requirement(
        "make.infra_up_waits",
        "makefile",
        "make infra-up waits for the composed application",
        lambda c: "docker compose up -d --wait web" in c.make_text,
        "returning before the stack is up makes the next command fail for the wrong reason",
    ),
    # --- build inputs ------------------------------------------------------------
    *[
        _requirement(
            f"dockerignore.{pattern.strip('.*/').replace('/', '_') or 'root'}",
            "build",
            f".dockerignore excludes {pattern}",
            lambda c, p=pattern: p in c.dockerignore,
            "anything not excluded is copied into the image and shipped",
        )
        for pattern in (".git", ".env", "infra/secrets/*.txt", "node_modules")
    ],
    _requirement(
        "dockerfile.api.hashed_lock",
        "build",
        "the API image installs the runtime lock with pinned hashes",
        lambda c: "requirements.runtime.lock" in c.api_dockerfile
        and "pip install --no-cache-dir --no-deps --require-hashes --requirement"
        in c.api_dockerfile
        and "pip check" in c.api_dockerfile,
        "a version pin says which release; a hash says which bytes",
    ),
    _requirement(
        "dockerfile.api.fixed_non_root_uid",
        "build",
        "the API image runs as a fixed non-root UID",
        lambda c: "USER 10001:10001" in c.api_dockerfile,
    ),
    _requirement(
        "dockerfile.web.reproducible_non_root",
        "build",
        "the web image builds reproducibly and runs non-root",
        lambda c: "npm ci" in c.web_dockerfile and "USER nginx:nginx" in c.web_dockerfile,
    ),
)
