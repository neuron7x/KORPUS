"""Exercise Compose's secret-to-Settings boundary through the real container entrypoint.

The PostgreSQL suite supplied three identities while Compose supplied only the app
login. Its API and worker could therefore never pass the mandatory broker guard.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from korpus.config import unknown_settings_variables
from korpus.infrastructure.rls_repository import RlsBoundSqlRepository
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]
ENTRYPOINT = ROOT / "apps/api/docker-entrypoint.sh"
ROLES = {
    "KORPUS_DATABASE": "korpus_app",
    "KORPUS_AUTHZ_DATABASE": "korpus_authz",
    "KORPUS_REVIEW_DATABASE": "korpus_review",
}
READ_SETTINGS = """
import json, os
from korpus.config import Settings, unknown_settings_variables
settings = Settings(_env_file=None, environment="test")
print(json.dumps({
    "urls": [settings.database_url, settings.authz_database_url, settings.review_database_url],
    "unknown": unknown_settings_variables(os.environ),
    "passwords": [key for key in os.environ if key.endswith("_DATABASE_PASSWORD")],
}))
"""


@pytest.fixture
def compose() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith(("KORPUS_", "AWS_"))
    }
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment["PATH"]
    environment["PYTHONPATH"] = str(ROOT / "apps/api/src")
    return environment


def _secret_targets(service: dict[str, Any]) -> dict[str, str]:
    return {
        item if isinstance(item, str) else item.get("target", item["source"]): (
            item if isinstance(item, str) else item["source"]
        )
        for item in service["secrets"]
    }


def _run(
    environment: dict[str, str], tmp_path: Path, code: str = READ_SETTINGS
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(ENTRYPOINT), sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


@pytest.mark.parametrize("service_name", ("api", "worker"))
def test_compose_resolves_distinct_database_identities(
    compose: dict[str, Any], service_name: str, tmp_path: Path
) -> None:
    service = compose["services"][service_name]
    mounts = _secret_targets(service)
    environment = _environment()
    passwords = {}
    for key, value in service["environment"].items():
        if not key.startswith(tuple(ROLES)):
            continue
        resolved_value = str(value)
        if key.endswith("_PASSWORD_FILE"):
            source = mounts[Path(value).name]
            assert source in compose["secrets"]
            passwords[key.removesuffix("_PASSWORD_FILE")] = f"{source}:?/p@#%&+ test"
            secret = tmp_path / source
            secret.write_text(passwords[key.removesuffix("_PASSWORD_FILE")] + "\n")
            resolved_value = str(secret)
        environment[key] = resolved_value
    result = _run(environment, tmp_path)
    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout)
    assert resolved["unknown"] == []
    assert resolved["passwords"] == []
    urls = resolved["urls"]
    RlsBoundSqlRepository._validate_authz_url(urls[0], urls[1])
    for url, (prefix, login) in zip(urls, ROLES.items(), strict=True):
        assert url is not None
        parsed = make_url(url)
        assert parsed.username == login
        assert parsed.password == passwords[prefix]
        assert (parsed.drivername, parsed.host, parsed.port, parsed.database) == (
            "postgresql+psycopg",
            "postgres",
            5432,
            "korpus",
        )


def test_migrate_provisions_the_same_runtime_roles_and_secrets(compose: dict[str, Any]) -> None:
    services = compose["services"]
    migrate = services["migrate"]
    environment = migrate["environment"]
    assert unknown_settings_variables(environment) == []
    provision_mounts = _secret_targets(migrate)
    for prefix, role in ROLES.items():
        role_name = role.removeprefix("korpus_").upper()
        assert environment[f"KORPUS_POSTGRES_{role_name}_ROLE"] == role
        path = environment[f"KORPUS_POSTGRES_{role_name}_PASSWORD_FILE"]
        provision_secret = provision_mounts[Path(path).name]
        for service_name in ("api", "worker"):
            service = services[service_name]
            runtime_path = service["environment"][f"{prefix}_PASSWORD_FILE"]
            assert _secret_targets(service)[Path(runtime_path).name] == provision_secret
            assert "postgres_admin_password" not in _secret_targets(service).values()


@pytest.mark.parametrize("prefix", ROLES)
@pytest.mark.parametrize(
    "failure", ("missing", "empty", "blank", "directory", "no_password", "no_marker", "two_markers")
)
def test_invalid_database_secrets_fail_before_command(
    prefix: str, failure: str, tmp_path: Path
) -> None:
    secret = tmp_path / "password"
    password = "synthetic-secret-value"
    template = "postgresql+psycopg://runtime:{password}@postgres/korpus"
    environment = _environment()
    environment[f"{prefix}_PASSWORD_FILE"] = str(secret)
    if failure == "directory":
        secret.mkdir()
    elif failure not in {"missing", "no_password"}:
        secret.write_text({"empty": "", "blank": " \t\n"}.get(failure, password))
    if failure == "no_password":
        del environment[f"{prefix}_PASSWORD_FILE"]
    if failure == "no_marker":
        template = template.replace("{password}", "wrong-literal-password")
    if failure == "two_markers":
        template += "?unexpected={password}"
    environment[f"{prefix}_URL_TEMPLATE"] = template
    result = _run(environment, tmp_path, "print('command started')")
    assert result.returncode == 64
    assert result.stdout == ""
    assert result.stderr
    assert password not in result.stderr
    assert "wrong-literal-password" not in result.stderr


def test_direct_urls_are_preserved_and_intermediate_passwords_are_removed(tmp_path: Path) -> None:
    environment = _environment()
    urls = []
    for prefix, role in ROLES.items():
        url = f"postgresql+psycopg://{role}:synthetic@postgres:5432/korpus"
        urls.append(url)
        environment[f"{prefix}_URL"] = url
        environment[f"{prefix}_PASSWORD"] = "unused-secret"
    result = _run(environment, tmp_path)
    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout)
    assert resolved == {"urls": urls, "unknown": [], "passwords": []}


def test_optional_templates_do_not_change_sqlite_startup(tmp_path: Path) -> None:
    environment = _environment()
    environment["KORPUS_DATABASE_URL"] = "sqlite:///:memory:"
    result = _run(environment, tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "urls": ["sqlite:///:memory:", None, None],
        "unknown": [],
        "passwords": [],
    }


def test_local_secret_bootstrap_is_complete_and_does_not_rotate_credentials(
    compose: dict[str, Any], tmp_path: Path
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "init_local_secrets.sh"
    shutil.copyfile(ROOT / "scripts/init_local_secrets.sh", script)
    for attempt in range(2):
        result = subprocess.run(
            ["bash", str(script)],
            cwd=tmp_path,
            env=_environment(),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        secrets = tmp_path / "infra/secrets"
        current = {path.name: path.read_bytes() for path in secrets.iterdir()}
        assert all(Path(item["file"]).name in current for item in compose["secrets"].values())
        if attempt == 0:
            original = current
        else:
            assert current == original
    credentials = [
        current[f"postgres_{role}_password.txt"] for role in ("admin", "app", "authz", "review")
    ]
    assert len(set(credentials)) == 4
    assert all(len(value.strip()) >= 48 for value in credentials)
    assert secrets.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o644 for path in secrets.iterdir())
