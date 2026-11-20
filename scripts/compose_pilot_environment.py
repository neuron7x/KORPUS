"""Private inputs and ownership checks for the disposable Compose qualification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

HOSTNAME = "pilot-smoke.example.test"
SERVICES = frozenset(
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
PROJECT_PATTERN = re.compile(r"korpus-smoke-[a-f0-9]{32}")
CONFIG_BINDS = {
    "minio-init": ("infra/minio/korpus-app-policy.json", "/config/korpus-app-policy.json"),
    "otel-collector": ("infra/otel-collector.yaml", "/etc/otelcol/config.yaml"),
}
RUNTIME_INSPECTION = """
import json
from korpus.config import Settings
from sqlalchemy.engine import make_url
s = Settings(_env_file=None)
print(json.dumps({
    "database": make_url(s.database_url).get_backend_name(),
    "object_store": s.object_store_mode,
    "malware_scan": s.malware_scan_mode,
    "ingestion": s.ingestion_mode,
    "auth": s.auth_mode,
    "review_separation": s.review_separation_required,
    "schema": s.schema_mode,
}))
"""


class SmokeFailure(RuntimeError):
    """A safe diagnostic without command output, credentials or response bodies."""


def require(condition: object, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def isolated_environment(environ: dict[str, str]) -> dict[str, str]:
    retained = {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "XDG_RUNTIME_DIR"}
    result = {key: value for key, value in environ.items() if key in retained}
    # Preserve the operator's CLI context and registry credential selection. Its
    # contents are never mounted into containers or included in the report.
    if "DOCKER_CONFIG" in environ:
        result["DOCKER_CONFIG"] = environ["DOCKER_CONFIG"]
    result["PATH"] = str(Path(sys.executable).parent) + os.pathsep + result.get("PATH", "")
    result["PILOT_HOSTNAME"] = HOSTNAME
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    return result


def check_port() -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 3000))
    except OSError as exc:
        raise SmokeFailure(
            "loopback port 3000 is unavailable; no existing service was stopped"
        ) from exc


@dataclass
class Workspace:
    source: Path
    state: Path
    project: str
    secret_files: dict[str, Path] = field(default_factory=dict)
    frozen_digest: str = ""

    @classmethod
    def create(cls, source: Path) -> Workspace:
        project = "korpus-smoke-" + uuid4().hex
        state = Path(tempfile.mkdtemp(prefix=project + "-"))
        (state / "owner").write_text(project, encoding="utf-8")
        (state / "empty.env").write_text("", encoding="utf-8")
        scripts = state / "scripts"
        scripts.mkdir()
        shutil.copyfile(source / "scripts/init_local_secrets.sh", scripts / "init_local_secrets.sh")
        shutil.copyfile(source / "docker-compose.yml", state / "base.compose.yaml")
        shutil.copyfile(
            source / "deploy/pilot/compose.private.yaml", state / "private.compose.yaml"
        )
        for relative, _target in CONFIG_BINDS.values():
            target = state / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
        return cls(source.resolve(), state, project)

    def assert_owned(self) -> None:
        require(
            bool(PROJECT_PATTERN.fullmatch(self.project)), "invalid disposable project identity"
        )
        require(not self.state.is_symlink(), "private state root changed")
        require(
            self.state.name.startswith(self.project + "-"),
            "private state does not belong to project",
        )
        marker = self.state / "owner"
        require(not marker.is_symlink() and marker.is_file(), "private ownership marker is absent")
        require(
            marker.read_text(encoding="utf-8") == self.project, "private ownership marker changed"
        )

    def prepare_override(self) -> None:
        self.assert_owned()
        base = yaml.safe_load((self.state / "base.compose.yaml").read_text(encoding="utf-8"))
        for name in base["secrets"]:
            require(bool(re.fullmatch(r"[a-z0-9_]+", name)), "unsupported Compose secret name")
            path = self.state / "infra/secrets" / (name + ".txt")
            require(
                path.is_file()
                and not path.is_symlink()
                and path.resolve().is_relative_to(self.state.resolve()),
                "secret generator omitted a declared secret",
            )
            require(bool(path.read_text(encoding="utf-8").strip()), "generated secret is empty")
            self.secret_files[name] = path
        override: dict[str, Any] = {
            "services": {
                name: {"environment": {"KORPUS_REVIEW_SEPARATION_REQUIRED": "true"}}
                for name in ("api", "worker")
            },
            "secrets": {name: {"file": str(path)} for name, path in self.secret_files.items()},
        }
        for service, (relative, target) in CONFIG_BINDS.items():
            override["services"][service] = {
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(self.state / relative),
                        "target": target,
                        "read_only": True,
                    }
                ]
            }
        (self.state / "secrets.json").write_text(json.dumps(override), encoding="utf-8")

    def arguments(self, *, frozen: bool = True) -> list[str]:
        self.assert_owned()
        if frozen:
            require(
                bool(self.frozen_digest) and self.input_digest() == self.frozen_digest,
                "frozen Compose input changed",
            )
        arguments = [
            "compose",
            "--project-name",
            self.project,
            "--project-directory",
            str(self.source),
            "--env-file",
            str(self.state / "empty.env"),
        ]
        for path in self.input_files():
            arguments.extend(("-f", str(path)))
        return arguments

    def input_files(self) -> list[Path]:
        return [
            self.state / name
            for name in ("base.compose.yaml", "private.compose.yaml", "secrets.json")
        ]

    def input_digest(self) -> str:
        digest = hashlib.sha256()
        configs = [self.state / relative for relative, _target in CONFIG_BINDS.values()]
        for path in [*self.input_files(), self.state / "empty.env", *configs]:
            require(
                not path.is_symlink() and path.resolve().is_relative_to(self.state.resolve()),
                "private Compose input escaped its root",
            )
            digest.update(path.name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()

    def freeze(self, configuration: dict[str, Any]) -> None:
        validate_configuration(configuration, self)
        # Reuse the inspected original inputs: feeding rendered JSON back to Compose
        # would interpolate shell dollars a second time (notably MinIO's secret reads).
        self.frozen_digest = self.input_digest()


def validate_resources(configuration: dict[str, Any], workspace: Workspace) -> None:
    for family in ("volumes", "networks"):
        for value in configuration[family].values():
            require(not value.get("external"), "external Compose resources are not disposable")
            require(
                value.get("name", "").startswith(workspace.project + "_"),
                "Compose resource name is outside the disposable project",
            )
    secrets = configuration["secrets"]
    require(set(secrets) == set(workspace.secret_files), "rendered secret set changed")
    for name, value in secrets.items():
        require(not value.get("external"), "external secrets are forbidden in the smoke")
        require(
            value.get("file") == str(workspace.secret_files[name]), "secret escaped private state"
        )


def validate_services(configuration: dict[str, Any], workspace: Workspace) -> None:
    allowed_binds = {str(workspace.state / relative) for relative, _target in CONFIG_BINDS.values()}
    for name, service in configuration["services"].items():
        require(not service.get("container_name"), "explicit container names are not disposable")
        require(not service.get("network_mode"), "shared network modes are forbidden in the smoke")
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                require(
                    mount.get("read_only") and mount["source"] in allowed_binds,
                    "unexpected host bind mount",
                )
            else:
                require(mount["type"] == "volume", "unsupported volume type")
                require(mount["source"] in configuration["volumes"], "undeclared volume")
        ports = service.get("ports", [])
        if name == "web":
            require(len(ports) == 1, "smoke requires one loopback web publication")
            port = ports[0]
            require(
                (port.get("host_ip"), str(port.get("published")), port.get("target"))
                == ("127.0.0.1", "3000", 8080),
                "web publication changed from loopback port 3000",
            )
        else:
            require(not ports, "backend service unexpectedly publishes a host port")


def validate_runtime(configuration: dict[str, Any]) -> None:
    expected = {
        "KORPUS_AUTH_MODE": "jwt",
        "KORPUS_SCHEMA_MODE": "migrations",
        "KORPUS_OBJECT_STORE_MODE": "s3",
        "KORPUS_MALWARE_SCAN_MODE": "clamd",
        "KORPUS_INGESTION_MODE": "durable_async",
        "KORPUS_REVIEW_SEPARATION_REQUIRED": "true",
        "KORPUS_TRUSTED_HOSTS": f"localhost,127.0.0.1,{HOSTNAME}",
        "KORPUS_CORS_ORIGINS": f"http://127.0.0.1:3000,http://localhost:3000,https://{HOSTNAME}",
    }
    for name in ("api", "worker"):
        environment = configuration["services"][name]["environment"]
        require(
            all(environment.get(key) == value for key, value in expected.items()),
            "runtime guards changed",
        )
        require(
            not any(key.startswith("KORPUS_MIN_") for key in environment),
            "the smoke must use canonical admission thresholds",
        )
    api = configuration["services"]["api"]["environment"]
    require(
        api.get("KORPUS_QUERY_PLANNER_API_KEY") == "",
        "model credential entered smoke configuration",
    )
    require(
        api.get("KORPUS_QUERY_PLANNER_ENABLED") == "false",
        "planner must retain its disabled default",
    )
    require(
        api.get("KORPUS_ANSWER_COMPOSER_ENABLED") == "false",
        "composer must retain its disabled default",
    )


def validate_configuration(configuration: dict[str, Any], workspace: Workspace) -> None:
    workspace.assert_owned()
    require(configuration.get("name") == workspace.project, "rendered project name changed")
    require(set(configuration["services"]) == SERVICES, "canonical Compose service set changed")
    validate_resources(configuration, workspace)
    validate_services(configuration, workspace)
    validate_runtime(configuration)


def sanitize(value: str, secrets: list[str]) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            value = value.replace(secret, "[redacted]")
    value = re.sub(
        r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", "[redacted JWT]", value
    )
    value = re.sub(
        r"(?i)postgres(?:ql)?(?:\+psycopg)?://[^\s\"']+", "[redacted database URL]", value
    )
    return value


def parse_services(output: str) -> dict[str, dict[str, Any]]:
    try:
        decoded = json.loads(output)
        rows = decoded if isinstance(decoded, list) else [decoded]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in output.splitlines() if line.strip()]
    return {
        row["Service"]: {
            "state": row.get("State"),
            "health": row.get("Health"),
            "exit_code": row.get("ExitCode"),
        }
        for row in rows
    }
