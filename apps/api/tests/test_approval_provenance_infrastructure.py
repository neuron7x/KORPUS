from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _secret_names(service: dict) -> set[str]:
    names: set[str] = set()
    for item in service.get("secrets", []) or []:
        names.add(item if isinstance(item, str) else str(item.get("source", "")))
    return names


def test_review_credential_is_provisioned_and_mounted_only_where_needed() -> None:
    compose = _compose()
    services = compose["services"]
    migrate = services["migrate"]
    api = services["api"]
    worker = services["worker"]

    assert migrate["environment"]["KORPUS_POSTGRES_REVIEW_ROLE"] == "korpus_review"
    assert "postgres_review_password" in _secret_names(migrate)
    assert "korpus_review:{password}" in api["environment"]["KORPUS_REVIEW_DATABASE_URL_TEMPLATE"]
    assert "postgres_review_password" in _secret_names(api)
    assert "postgres_review_password" not in _secret_names(worker)
    assert "KORPUS_REVIEW_DATABASE_URL_TEMPLATE" not in worker["environment"]


def test_entrypoint_builds_review_url_without_leaving_password_intermediates() -> None:
    entrypoint = (ROOT / "apps/api/docker-entrypoint.sh").read_text(encoding="utf-8")
    secret_init = (ROOT / "scripts/init_local_secrets.sh").read_text(encoding="utf-8")

    assert "KORPUS_REVIEW_DATABASE_PASSWORD_FILE" in entrypoint
    assert "build_database_url \\\n  KORPUS_REVIEW_DATABASE_URL" in entrypoint
    assert "unset KORPUS_DATABASE_PASSWORD KORPUS_REVIEW_DATABASE_PASSWORD" in entrypoint
    assert "postgres_review_password" in secret_init
