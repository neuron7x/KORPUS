"""Isolation and verdict controls; real Compose execution belongs to its hosted workflow."""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import compose_pilot_environment as environment  # noqa: E402
import run_compose_pilot_smoke as runner  # noqa: E402
from compose_pilot_environment import SmokeFailure, Workspace  # noqa: E402


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Workspace]:
    source = tmp_path / "operator-checkout"
    for relative in (
        "scripts/init_local_secrets.sh",
        "docker-compose.yml",
        "deploy/pilot/compose.private.yaml",
        *(relative for relative, _ in environment.CONFIG_BINDS.values()),
    ):
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    (source / ".env").write_text("KORPUS_QUERY_PLANNER_API_KEY=operator-credential\n")
    operator_secrets = source / "infra/secrets"
    operator_secrets.mkdir()
    (operator_secrets / "jwt_secret.txt").write_text("operator-signing-secret")
    monkeypatch.setattr(environment.tempfile, "tempdir", str(tmp_path))
    private = Workspace.create(source)
    secret_directory = private.state / "infra/secrets"
    secret_directory.mkdir(mode=0o700)
    for name in yaml.safe_load((source / "docker-compose.yml").read_text())["secrets"]:
        path = secret_directory / f"{name}.txt"
        path.write_text(f"synthetic-{name}-{'x' * 48}\n")
        path.chmod(0o644)
    private.prepare_override()
    yield private
    if private.state.is_dir() and not private.state.is_symlink():
        shutil.rmtree(private.state)


def rendered_configuration(workspace: Workspace) -> dict[str, Any]:
    """A normalized protocol fixture, never evidence that Docker rendered or ran it."""
    services: dict[str, Any] = {name: {} for name in environment.SERVICES}
    for name in ("api", "worker"):
        services[name]["environment"] = {
            "KORPUS_AUTH_MODE": "jwt",
            "KORPUS_SCHEMA_MODE": "migrations",
            "KORPUS_OBJECT_STORE_MODE": "s3",
            "KORPUS_MALWARE_SCAN_MODE": "clamd",
            "KORPUS_INGESTION_MODE": "durable_async",
            "KORPUS_REVIEW_SEPARATION_REQUIRED": "true",
            "KORPUS_TRUSTED_HOSTS": f"localhost,127.0.0.1,{environment.HOSTNAME}",
            "KORPUS_CORS_ORIGINS": f"http://127.0.0.1:3000,http://localhost:3000,https://{environment.HOSTNAME}",
        }
    services["api"]["environment"].update(
        KORPUS_QUERY_PLANNER_API_KEY="",
        KORPUS_QUERY_PLANNER_ENABLED="false",
        KORPUS_ANSWER_COMPOSER_ENABLED="false",
    )
    services["web"]["ports"] = [{"host_ip": "127.0.0.1", "published": "3000", "target": 8080}]
    for service, (relative, target) in environment.CONFIG_BINDS.items():
        services[service]["volumes"] = [
            {
                "type": "bind",
                "source": str(workspace.state / relative),
                "target": target,
                "read_only": True,
            }
        ]
    return {
        "name": workspace.project,
        "services": services,
        "volumes": {"data": {"name": workspace.project + "_data"}},
        "networks": {"backend": {"name": workspace.project + "_backend", "internal": True}},
        "secrets": {name: {"file": str(path)} for name, path in workspace.secret_files.items()},
    }


def prepared_smoke(workspace: Workspace) -> runner.ComposeSmoke:
    workspace.freeze(rendered_configuration(workspace))
    smoke = runner.ComposeSmoke(workspace.source, 600, 5)
    smoke.workspace = workspace
    smoke.docker = ["docker", "--host", "unix:///synthetic-docker.sock"]
    return smoke


def test_caller_credentials_and_compose_controls_do_not_enter_child_processes() -> None:
    poison = {
        key: "operator-value"
        for key in (
            "KORPUS_TEST_DATABASE_URL",
            "KORPUS_QUERY_PLANNER_API_KEY",
            "KORPUS_AUTH_MODE",
            "COMPOSE_FILE",
            "COMPOSE_PROJECT_NAME",
            "COMPOSE_PROFILES",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "AWS_SECRET_ACCESS_KEY",
            "HTTP_PROXY",
            "PYTHONPATH",
        )
    }
    result = environment.isolated_environment(
        {"PATH": "/bin", "HOME": "/synthetic-home", "DOCKER_CONFIG": "/private/docker", **poison}
    )
    assert not (poison.keys() & result.keys())
    assert result["PILOT_HOSTNAME"] == "pilot-smoke.example.test"
    assert result["DOCKER_CONFIG"] == "/private/docker"


def test_actual_secret_generator_uses_only_private_copies(workspace: Workspace) -> None:
    for path in workspace.secret_files.values():
        path.unlink()
    for relative, _ in environment.CONFIG_BINDS.values():
        (workspace.source / relative).chmod(0o600)
    subprocess.run(
        ["bash", str(workspace.state / "scripts/init_local_secrets.sh")],
        check=True,
        capture_output=True,
        env=environment.isolated_environment(dict(os.environ)),
    )
    workspace.prepare_override()
    values = {path.read_text().strip() for path in workspace.secret_files.values()}
    assert len(values) == len(workspace.secret_files)
    assert all(len(value) >= 30 for value in values)
    assert stat.S_IMODE(workspace.state.stat().st_mode) == 0o700
    assert stat.S_IMODE((workspace.state / "infra/secrets").stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o644 for path in workspace.secret_files.values()
    )
    assert (
        workspace.source / "infra/secrets/jwt_secret.txt"
    ).read_text() == "operator-signing-secret"
    assert (workspace.source / ".env").read_text().endswith("operator-credential\n")
    for relative, _ in environment.CONFIG_BINDS.values():
        assert (workspace.source / relative).read_bytes() == (
            workspace.state / relative
        ).read_bytes()
        assert stat.S_IMODE((workspace.source / relative).stat().st_mode) == 0o600
        assert stat.S_IMODE((workspace.state / relative).stat().st_mode) == 0o644


def test_original_dollars_and_explicit_empty_env_survive_freezing(workspace: Workspace) -> None:
    workspace.freeze(rendered_configuration(workspace))
    command = workspace.arguments()
    assert command[command.index("--project-name") + 1] == workspace.project
    assert command[command.index("--project-directory") + 1] == str(workspace.source)
    assert Path(command[command.index("--env-file") + 1]).read_text() == ""
    snapshot = (workspace.state / "base.compose.yaml").read_bytes()
    assert snapshot == (workspace.source / "docker-compose.yml").read_bytes()
    assert b"$$(cat /run/secrets/minio_root_password)" in snapshot
    assert all(
        str(workspace.state) in command[index + 1]
        for index, value in enumerate(command)
        if value == "-f"
    )


@pytest.mark.parametrize(
    "relative",
    [
        "base.compose.yaml",
        "private.compose.yaml",
        "secrets.json",
        "empty.env",
        "infra/otel-collector.yaml",
    ],
)
def test_changed_frozen_input_blocks_commands(workspace: Workspace, relative: str) -> None:
    workspace.freeze(rendered_configuration(workspace))
    path = workspace.state / relative
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(SmokeFailure, match="frozen Compose input changed"):
        workspace.arguments()


@pytest.mark.parametrize(
    "poison",
    [
        "foreign_volume",
        "external_volume",
        "foreign_network",
        "operator_secret",
        "host_port",
        "backend_port",
        "writable_bind",
        "operator_bind",
        "host_network",
        "container_name",
        "threshold",
        "model_key",
        "dev_auth",
        "wildcard_host",
    ],
)
def test_unsafe_configuration_cannot_be_adopted(workspace: Workspace, poison: str) -> None:
    configuration = rendered_configuration(workspace)
    services = configuration["services"]
    mutations = {
        "foreign_volume": (configuration["volumes"]["data"], "name", "operator_data"),
        "external_volume": (configuration["volumes"]["data"], "external", True),
        "foreign_network": (configuration["networks"]["backend"], "name", "operator_network"),
        "operator_secret": (
            configuration["secrets"]["jwt_secret"],
            "file",
            str(workspace.source / "infra/secrets/jwt_secret.txt"),
        ),
        "host_port": (services["web"]["ports"][0], "host_ip", "0.0.0.0"),
        "backend_port": (services["postgres"], "ports", [{"published": "5432"}]),
        "writable_bind": (services["minio-init"]["volumes"][0], "read_only", False),
        "operator_bind": (services["minio-init"]["volumes"][0], "source", "/operator/data"),
        "host_network": (services["api"], "network_mode", "host"),
        "container_name": (services["api"], "container_name", "operator-api"),
        "threshold": (services["api"]["environment"], "KORPUS_MIN_RETRIEVAL_SCORE", "0"),
        "model_key": (
            services["api"]["environment"],
            "KORPUS_QUERY_PLANNER_API_KEY",
            "operator-secret",
        ),
        "dev_auth": (services["api"]["environment"], "KORPUS_AUTH_MODE", "dev"),
        "wildcard_host": (services["api"]["environment"], "KORPUS_TRUSTED_HOSTS", "*"),
    }
    target, key, value = mutations[poison]
    target[key] = value
    with pytest.raises(SmokeFailure):
        workspace.freeze(configuration)
    assert workspace.frozen_digest == ""


def test_secret_symlink_is_refused(workspace: Workspace) -> None:
    path = workspace.secret_files["jwt_secret"]
    path.unlink()
    path.symlink_to(workspace.source / "infra/secrets/jwt_secret.txt")
    with pytest.raises(SmokeFailure, match="omitted a declared secret"):
        workspace.prepare_override()


def test_changed_ownership_prevents_destructive_cleanup(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke = prepared_smoke(workspace)
    smoke.started = True
    (workspace.state / "owner").write_text("operator-project")
    calls: list[list[str]] = []
    monkeypatch.setattr(smoke, "execute", lambda arguments, timeout=30: calls.append(arguments))
    with pytest.raises(SmokeFailure, match="ownership marker changed"):
        smoke.cleanup()
    assert calls == []
    assert workspace.state.exists()


def test_busy_port_is_not_stopped_or_reused() -> None:
    with socket.socket() as listener:
        # An already bound listener is the same negative control.
        with suppress(OSError):
            listener.bind(("127.0.0.1", 3000))
        with pytest.raises(SmokeFailure, match="no existing service was stopped"):
            environment.check_port()


@pytest.mark.parametrize(
    "key", ["DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"]
)
def test_explicit_docker_endpoint_override_fails_before_any_command(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(key, "operator-endpoint")
    smoke = runner.ComposeSmoke(ROOT, 600, 5)
    calls: list[list[str]] = []
    monkeypatch.setattr(smoke, "execute", lambda arguments, timeout=30: calls.append(arguments))
    with pytest.raises(SmokeFailure, match="endpoint environment overrides"):
        smoke.preflight()
    assert calls == []


def test_remote_context_is_refused_without_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(runner, "check_port", lambda: None)
    monkeypatch.setattr(runner.shutil, "which", lambda *args, **kwargs: "/synthetic/docker")
    smoke = runner.ComposeSmoke(ROOT, 600, 5)
    calls: list[list[str]] = []

    def execute(arguments: list[str], timeout: int = 30) -> str:
        calls.append(arguments)
        return "ssh://operator-host\n"

    monkeypatch.setattr(smoke, "execute", execute)
    with pytest.raises(SmokeFailure, match="local Unix Docker endpoint"):
        smoke.preflight()
    assert len(calls) == 1 and calls[0][1:3] == ["context", "inspect"]


def test_start_failure_cleans_only_own_project(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke = prepared_smoke(workspace)
    monkeypatch.setattr(smoke, "preflight", lambda: None)
    monkeypatch.setattr(smoke, "prepare", lambda: None)
    monkeypatch.setattr(runner, "check_port", lambda: None)
    calls: list[list[str]] = []

    def execute(arguments: list[str], timeout: int = 30) -> str:
        calls.append(arguments)
        if "up" in arguments:
            raise SmokeFailure("synthetic startup failure")
        return ""

    monkeypatch.setattr(smoke, "execute", execute)
    result = smoke.run()
    assert result["status"] == "FAIL"
    assert result["cleanup"] == "owned_project_removed"
    assert not workspace.state.exists()
    down = [command for command in calls if "down" in command]
    assert len(down) == 1
    assert down[0][down[0].index("--project-name") + 1] == workspace.project
    assert down[0][-4:] == ["down", "--volumes", "--timeout", "30"]
    for command in calls:
        if "--filter" in command:
            assert command[-1] == "label=com.docker.compose.project=" + workspace.project


def test_existing_project_is_never_adopted_or_torn_down(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke = runner.ComposeSmoke(workspace.source, 600, 5)
    monkeypatch.setattr(smoke, "preflight", lambda: None)
    monkeypatch.setattr(smoke, "resources", lambda: {"containers": ["preexisting"]})
    calls: list[list[str]] = []

    def execute(arguments: list[str], timeout: int = 30) -> str:
        calls.append(arguments)
        if arguments[0] == "bash":
            subprocess.run(arguments, check=True, capture_output=True, env=smoke.environment)
            return ""
        assert smoke.workspace is not None
        return json.dumps(rendered_configuration(smoke.workspace))

    monkeypatch.setattr(smoke, "execute", execute)
    result = smoke.run()
    assert result["status"] == "FAIL"
    assert "refusing to adopt" in result["failure"]
    assert not any("up" in command or "down" in command for command in calls)


def test_incomplete_cleanup_changes_pass_to_fail_and_preserves_state(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke = prepared_smoke(workspace)
    smoke.started = True
    smoke.report["status"] = "PASS"
    for name in ("preflight", "prepare", "start", "inspect_runtime", "acceptance"):
        monkeypatch.setattr(smoke, name, lambda: None)

    def failed_down(arguments: list[str], timeout: int = 30) -> str:
        raise SmokeFailure("synthetic cleanup failure")

    monkeypatch.setattr(smoke, "execute", failed_down)
    result = smoke.run()
    assert result["status"] == "FAIL" and result["cleanup"] == "incomplete"
    assert result["private_state_retained"] == str(workspace.state)
    assert workspace.state.exists()


@pytest.mark.parametrize(
    "status,mode,accepted",
    [
        ("PASS", "durable_async", True),
        ("FAIL", "durable_async", False),
        ("PASS", "synchronous", False),
    ],
)
def test_journey_requires_live_probe_pass_and_real_worker(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, status: str, mode: str, accepted: bool
) -> None:
    smoke = prepared_smoke(workspace)
    minted: list[list[str]] = []

    def mint(arguments: list[str], timeout: int = 30) -> str:
        minted.append(arguments)
        return f"syntheticHeader.syntheticPayload{len(minted)}.syntheticSignature"

    monkeypatch.setattr(smoke, "compose", mint)
    monkeypatch.setattr(
        runner.PacedAcceptance, "run", lambda self: {"status": status, "ingestion_mode": mode}
    )
    if accepted:
        smoke.acceptance()
        assert smoke.report["status"] == "PASS"
    else:
        with pytest.raises(SmokeFailure):
            smoke.acceptance()
        assert smoke.report["status"] == "FAIL"
    assert len(minted) == 10
    subjects = {command[command.index("--subject") + 1] for command in minted}
    assert len(subjects) == 10
    for command in minted:
        assert command[:6] == [
            "exec",
            "-T",
            "api",
            "/usr/local/bin/korpus-entrypoint",
            "python",
            "/app/scripts/mint_review_token.py",
        ]
        assert command[-2:] == ["--minutes", "10"]
        assert not any(token in command for token in smoke.secrets)
    assert minted[0][minted[0].index("--roles") + 1] == "curator"
    assert all(command[command.index("--roles") + 1] == "user" for command in minted[1:6])
    assert minted[-1][minted[-1].index("--corpora") + 1] == "pilot-smoke-outsider"


def test_report_sanitization_and_service_projection_do_not_expose_credentials() -> None:
    secret = "synthetic-secret-value"
    token = "syntheticHeader.syntheticPayload.syntheticSignature"
    value = environment.sanitize(
        f"{secret} {token} postgresql+psycopg://user:pass@host/db", [secret]
    )
    assert secret not in value and token not in value and "user:pass" not in value
    row = {
        "Service": "api",
        "State": "running",
        "Health": "healthy",
        "ExitCode": 0,
        "Command": token,
    }
    assert token not in json.dumps(environment.parse_services(json.dumps(row)))
    assert environment.parse_services(json.dumps([row])) == environment.parse_services(
        json.dumps(row)
    )


def test_failure_evidence_preserves_first_error_without_secret_or_command_leaks(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke = prepared_smoke(workspace)
    smoke.started = True
    secret = workspace.secret_files["jwt_secret"].read_text().strip()
    token = "syntheticHeader.syntheticPayload.syntheticSignature"
    smoke.secrets = [secret]
    message = f"startup refused {secret} {token} postgresql://user:password@host/db"
    completed = subprocess.CompletedProcess(["docker"], 1, stdout="", stderr=message)
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: completed)
    with pytest.raises(SmokeFailure):
        smoke.execute(["docker"])
    first = smoke.report["diagnostic"]
    row = {
        "Service": "api",
        "State": "exited",
        "Health": "unhealthy",
        "ExitCode": 1,
        "Command": token,
    }
    monkeypatch.setattr(
        smoke, "compose", lambda args, timeout=30: json.dumps(row) if args[0] == "ps" else message
    )
    smoke.failure_logs()
    assert smoke.report["diagnostic"] == first
    assert smoke.report["command_exit_code"] == 1
    assert smoke.report["service_states_at_failure"]["api"]["exit_code"] == 1
    rendered = json.dumps(smoke.report)
    assert secret not in rendered and token not in rendered and "user:password" not in rendered
    assert "Command" not in rendered


def test_cleanup_requires_every_owned_resource_to_be_gone(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke = prepared_smoke(workspace)
    smoke.started = True
    monkeypatch.setattr(smoke, "compose", lambda args, timeout=30: "")
    monkeypatch.setattr(smoke, "resources", lambda: {"volumes": ["surviving-owned-volume"]})
    with pytest.raises(SmokeFailure, match="resources remain after cleanup"):
        smoke.cleanup()
    assert workspace.state.exists()


def test_private_hostname_overlay_only_changes_explicit_origins() -> None:
    overlay = yaml.safe_load((ROOT / "deploy/pilot/compose.private.yaml").read_text())
    assert set(overlay) == {"services"}
    assert set(overlay["services"]) == {"api", "worker"}
    for service in overlay["services"].values():
        assert set(service) == {"environment"}
        assert set(service["environment"]) == {"KORPUS_TRUSTED_HOSTS", "KORPUS_CORS_ORIGINS"}
        for value in service["environment"].values():
            assert "${PILOT_HOSTNAME:?" in value and "*" not in value
