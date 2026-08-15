from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "docker-compose.yml"
ENTRYPOINT = ROOT / "apps/api/docker-entrypoint.sh"


def _compose() -> dict[str, object]:
    loaded = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _service(compose: dict[str, object], name: str) -> dict[str, object]:
    services = compose.get("services")
    assert isinstance(services, dict)
    service = services.get(name)
    assert isinstance(service, dict)
    return service


def _secret_names(service: dict[str, object]) -> set[str]:
    raw = service.get("secrets", [])
    assert isinstance(raw, list)
    names: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict):
            source = item.get("source")
            assert isinstance(source, str)
            names.add(source)
        else:
            raise AssertionError(f"unexpected compose secret entry: {item!r}")
    return names


def test_migration_provisions_the_identity_broker_login_from_a_secret() -> None:
    compose = _compose()
    migrate = _service(compose, "migrate")
    environment = migrate.get("environment")
    assert isinstance(environment, dict)
    assert environment["KORPUS_POSTGRES_IDENTITY_ROLE"] == "korpus_identity"
    assert environment["KORPUS_POSTGRES_IDENTITY_PASSWORD_FILE"] == (
        "/run/secrets/postgres_identity_password"
    )
    assert "postgres_identity_password" in _secret_names(migrate)


def test_api_and_worker_receive_only_broker_url_template_and_secret_file() -> None:
    compose = _compose()
    expected_template = (
        "postgresql+psycopg://korpus_identity:{password}@postgres:5432/korpus"
    )
    for name in ("api", "worker"):
        service = _service(compose, name)
        environment = service.get("environment")
        assert isinstance(environment, dict)
        assert environment["RLS_IDENTITY_DATABASE_URL_TEMPLATE"] == expected_template
        assert environment["RLS_IDENTITY_DATABASE_PASSWORD_FILE"] == (
            "/run/secrets/postgres_identity_password"
        )
        assert "RLS_IDENTITY_DATABASE_URL" not in environment
        assert "postgres_identity_password" in _secret_names(service)


def test_identity_broker_secret_is_declared_once_at_compose_boundary() -> None:
    compose = _compose()
    secrets = compose.get("secrets")
    assert isinstance(secrets, dict)
    secret = secrets.get("postgres_identity_password")
    assert secret == {"file": "./infra/secrets/postgres_identity_password.txt"}


def test_entrypoint_materializes_and_then_drops_broker_password_variables() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    read = "read_secret RLS_IDENTITY_DATABASE_PASSWORD RLS_IDENTITY_DATABASE_PASSWORD_FILE"
    assert read in source
    build = source.index("build_database_url", source.index(read))
    url = source.index("RLS_IDENTITY_DATABASE_URL", build)
    template = source.index("RLS_IDENTITY_DATABASE_URL_TEMPLATE", url)
    password = source.index("RLS_IDENTITY_DATABASE_PASSWORD", template)
    assert build < url < template < password
    unset_lines = [line for line in source.splitlines() if line.startswith("unset ")]
    assert any("RLS_IDENTITY_DATABASE_PASSWORD" in line for line in unset_lines)
    assert any("RLS_IDENTITY_DATABASE_URL_TEMPLATE" in line for line in unset_lines)
    assert any("RLS_IDENTITY_DATABASE_PASSWORD_FILE" in line for line in unset_lines)
