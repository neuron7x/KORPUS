#!/usr/bin/env python3
"""Fail-closed static infrastructure contract validation."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
EXACT_TAG = re.compile(r"^[^:@\s]+:[^:@\s]+$")


def main() -> int:
    failures: list[str] = []
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services: dict[str, dict] = compose.get("services", {})
    required = {
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
    missing = sorted(required - services.keys())
    if missing:
        failures.append(f"missing services: {missing}")

    for name, service in services.items():
        if service.get("privileged"):
            failures.append(f"{name}: privileged mode forbidden")
        if name != "web" and service.get("ports"):
            failures.append(f"{name}: host ports forbidden")
        for port in service.get("ports", []) or []:
            if name == "web" and not str(port).startswith("127.0.0.1:"):
                failures.append("web: published port must bind loopback")
        security = service.get("security_opt", []) or []
        if "no-new-privileges:true" not in security:
            failures.append(f"{name}: no-new-privileges missing")
        if service.get("restart") != "no" and not service.get("init"):
            failures.append(f"{name}: init process missing")
        if not service.get("mem_limit") or not service.get("cpus"):
            failures.append(f"{name}: resource ceiling missing")
        image = service.get("image")
        if image and (not EXACT_TAG.fullmatch(image) or image.endswith(":latest")):
            failures.append(f"{name}: image is not exactly tagged: {image}")

    api = services.get("api", {})
    env = api.get("environment", {}) or {}
    for key, expected in {
        "KORPUS_SCHEMA_MODE": "migrations",
        "KORPUS_OBJECT_STORE_MODE": "s3",
        "KORPUS_S3_FORCE_PATH_STYLE": "true",
    }.items():
        if str(env.get(key, "")).lower() != expected:
            failures.append(f"api: {key} must be {expected}")
    if "postgresql+psycopg" not in str(env.get("KORPUS_DATABASE_URL_TEMPLATE", "")):
        failures.append("api: PostgreSQL application URL missing")
    depends = api.get("depends_on", {}) or {}
    for dependency in ("migrate", "minio-init", "otel-collector"):
        if dependency not in depends:
            failures.append(f"api: dependency {dependency} missing")
    if not api.get("read_only"):
        failures.append("api: read_only root filesystem missing")


    worker = services.get("worker", {})
    worker_env = worker.get("environment", {}) or {}
    expected_worker_command = ["python", "-m", "korpus.cli", "worker-loop", "--idle-seconds", "1"]
    if worker.get("command") != expected_worker_command:
        failures.append("worker: durable ingestion command missing")
    if str(worker_env.get("KORPUS_INGESTION_MODE", "")).lower() != "durable_async":
        failures.append("worker: durable ingestion mode missing")
    if set(worker.get("networks", []) or []) != {"backend", "egress"}:
        failures.append("worker: must be isolated from edge network")
    if not (worker.get("healthcheck", {}) or {}).get("disable"):
        failures.append("worker: inherited HTTP healthcheck must be disabled")
    if "clamav" not in (worker.get("depends_on", {}) or {}):
        failures.append("worker: ClamAV dependency missing")
    for key, expected in {
        "KORPUS_INGESTION_MODE": "durable_async",
        "KORPUS_MALWARE_SCAN_MODE": "clamd",
        "KORPUS_PARSER_SANDBOX_ENABLED": "true",
    }.items():
        if str(env.get(key, "")).lower() != expected:
            failures.append(f"api: {key} must be {expected}")
    if "clamav" not in depends:
        failures.append("api: ClamAV dependency missing")


    # Least-privilege object storage: the API must never mount MinIO root credentials.
    api_secrets_json = json.dumps(api.get("secrets", []), sort_keys=True)
    api_secret_text = api_secrets_json + json.dumps(env, sort_keys=True)
    if "minio_root_password" in api_secret_text:
        failures.append("api: MinIO root credentials must not be mounted")
    for name in ("minio_app_access_key", "minio_app_secret_key"):
        if name not in api_secret_text:
            failures.append(f"api: dedicated MinIO credential missing: {name}")
    policy_path = ROOT / "infra/minio/korpus-app-policy.json"
    try:
        policy_text = policy_path.read_text(encoding="utf-8")
        policy = json.loads(policy_text)
        actions = {
            action
            for statement in policy.get("Statement", [])
            for action in statement.get("Action", [])
        }
        resources = {
            resource
            for statement in policy.get("Statement", [])
            for resource in statement.get("Resource", [])
        }
        if "s3:DeleteObject" in actions or "s3:*" in actions:
            failures.append("MinIO application policy permits destructive/wildcard object access")
        for required_action in ("s3:GetBucketVersioning", "s3:GetObjectLockConfiguration"):
            if required_action not in actions:
                failures.append(
                    f"MinIO application policy missing durability check: {required_action}"
                )
        for prefix in ("arn:aws:s3:::korpus/objects/*", "arn:aws:s3:::korpus/quarantine/*"):
            if prefix not in resources:
                failures.append(
                    f"MinIO application policy missing required restricted prefix: {prefix}"
                )
        if any(resource.endswith("/*") and resource not in {
            "arn:aws:s3:::korpus/objects/*", "arn:aws:s3:::korpus/quarantine/*"
        } for resource in resources):
            failures.append("MinIO application policy includes an unexpected object prefix")
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"MinIO application policy is missing or invalid: {exc}")

    postgres = services.get("postgres", {})
    allowed_postgres_caps = {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"}
    if set(postgres.get("cap_add", []) or []) - allowed_postgres_caps:
        failures.append("postgres: unexpected Linux capability added")

    ci_text = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    if "\ncache:\n" in ci_text:
        failures.append("GitLab CI global cache is forbidden in the assurance pipeline")
    for forbidden in ("privileged: true", "docker:dind"):
        if forbidden in ci_text:
            failures.append(f"GitLab CI forbidden construct present: {forbidden}")
    for required_ci in ("moby/buildkit", "gitleaks", "trivy", "syft", "verify_postgres_restore.py"):
        if required_ci not in ci_text:
            failures.append(f"GitLab CI missing required gate: {required_ci}")
    postgres_job_header = 'api:postgres-and-restore:\n  stage: assurance\n  image:\n    name:'
    if postgres_job_header not in ci_text or 'entrypoint: [""]' not in ci_text:
        failures.append("PostgreSQL CI job must clear the database image entrypoint")

    package_text = (ROOT / "scripts/package_repository.sh").read_text(encoding="utf-8")
    if "git archive --format=tar HEAD" not in package_text:
        failures.append("release packaging must originate from committed Git tree")
    if "verify_release_evidence.py" not in package_text:
        failures.append("release packaging must reject stale assurance evidence")
    if 'rm -rf "$tmp/reports"' not in package_text:
        failures.append(
            "release packaging must replace committed reports instead of nesting stale evidence"
        )

    for script_name in ("backup_postgres.sh", "restore_postgres.sh"):
        text_value = (ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        if "KORPUS_BACKUP_ENCRYPTION_KEY_FILE" not in text_value:
            failures.append(f"{script_name}: encrypted backup key is not mandatory")
    manifest_text = (ROOT / "scripts/backup_manifest.py").read_text(encoding="utf-8")
    if (
        "korpus-postgres-backup-v4" not in manifest_text
        or "manifest_hmac_sha256" not in manifest_text
    ):
        failures.append("backup_manifest.py: authenticated current manifest schema missing")
    backup_text = (ROOT / "scripts/backup_postgres.sh").read_text(encoding="utf-8")
    restore_text = (ROOT / "scripts/restore_postgres.sh").read_text(encoding="utf-8")
    if "KORPUS_BACKUP_KEY_ID" not in backup_text or "KORPUS_BACKUP_KEY_ID" not in restore_text:
        failures.append("backup/restore: encryption key identity must be mandatory")
    if "--file=-" not in backup_text or "encrypt-stdin" not in backup_text:
        failures.append("backup_postgres.sh: plaintext-free streaming backup pipeline missing")
    if "backup_manifest.py" not in backup_text or "backup_manifest.py" not in restore_text:
        failures.append("backup/restore: authenticated manifest verification missing")

    make_text = (ROOT / "Makefile").read_text(encoding="utf-8")
    if "--profile support" in make_text:
        failures.append("Makefile references nonexistent Compose support profile")
    if "docker compose up -d --wait web" not in make_text:
        failures.append("Makefile infra-up does not wait for the composed application")

    web = services.get("web", {})
    if set(web.get("networks", []) or []) != {"edge"}:
        failures.append("web: must be isolated to the internal edge network")
    networks = compose.get("networks", {}) or {}
    for network_name in ("edge", "backend"):
        if (networks.get(network_name, {}) or {}).get("internal") is not True:
            failures.append(f"{network_name} network must be internal")
    if "egress" not in set(api.get("networks", []) or []):
        failures.append("api: dedicated egress network missing")

    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for required_pattern in (".git", ".env", "infra/secrets/*.txt", "node_modules"):
        if required_pattern not in dockerignore:
            failures.append(f".dockerignore missing {required_pattern}")

    api_docker = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    if (
        "requirements.runtime.lock" not in api_docker
        or "pip install --no-cache-dir --no-deps --requirement" not in api_docker
        or "pip check" not in api_docker
    ):
        failures.append("API Dockerfile does not install exact runtime lock")
    if "USER 10001:10001" not in api_docker:
        failures.append("API Dockerfile does not run as fixed non-root UID")

    web_docker = (ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8")
    if "npm ci" not in web_docker or "USER nginx:nginx" not in web_docker:
        failures.append("web Dockerfile lacks reproducible non-root build/runtime")

    report = {"valid": not failures, "services": sorted(services), "failures": failures}
    output = ROOT / "var/infrastructure-validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
